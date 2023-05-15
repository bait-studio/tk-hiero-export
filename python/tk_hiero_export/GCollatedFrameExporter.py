# Copyright (c) 2011 The Foundry Visionmongers Ltd.  All Rights Reserved.

import math
import os
import os.path
import re

import hiero.core
import hiero.core.util
import hiero.core.log

from hiero.exporters import FnShotExporter

from .helpers import Collate

class GCollatedFrameExporter(FnShotExporter.ShotTask):
  """ 
  Custom version of the FnFrameExporter, that adds explicit collate copy functionality.
  """
  def __init__( self, initDict ):
    """Initialize"""
    FnShotExporter.ShotTask.__init__( self, initDict )

    self._paths = [] # List of (srcPath, dstPath) tuples
    self._currentPathIndex = 0

    if not self._source.isMediaPresent() and self._skipOffline:
      return

    # build a dict containing all paths from the main and collated track items
    self._buildCollatedFileSequencePaths()
    
  def _buildCollatedFileSequencePaths(self):
    # get collate info for the entire sequence
    sequenceCollateInfo = Collate.getCollateInfoFromSequenceAndMainTrack(self._item.parentSequence(), self._item.parentTrack())
    
    # extract info just for this shot
    self._collateInfo = sequenceCollateInfo[self._item.guid()]
    
    # store paths for the main item
    self._buildFileSequencePaths(self._collateInfo["mainItem"])
    
    # additionally store paths for all overlapping items
    for item in self._collateInfo["overlappingItems"]:
      self._buildFileSequencePaths(item, parentItemInfo=self._collateInfo["mainItem"])

  def _buildFileSequencePaths(self, collateInfo, parentItemInfo=None):
    """ Build the list of src/dst paths for each frame in a file sequence """
    # pull out the track items from the collate info
    item = collateInfo["trackItem"]
    parentItem = parentItemInfo["trackItem"] if parentItemInfo else None

    # todo - determine resolved export path for the passed in item
    # we can use Hiero's resolvers to do this.
    # there's likely a way we can easily spawn a task here to use with FnResolveTable.resolve
    # but I don't have time to figure that out right now.
    # instead I'll duplicate the current resolve table, and override the values
    # that actually change between the items we'll pass into this function.
    # right now, that's just {track}
    resolver = self._resolver
    resolverDuplicate = resolver.duplicate()
    resolverDuplicate.addResolver("{track}", "replaces track token with track name, filling spaces with underscores", item.parentTrack().name().replace(" ", "_"))
    thisItemResolvedExportPath = resolverDuplicate.resolve(self, self._exportPath, isPath=True)
    
    # at this point the path is likely a mix of forward/backslashes due to how nuke/SG handle things differently.
    # make them all forward slashes (i.e. nuke style)
    thisItemResolvedExportPath = thisItemResolvedExportPath.replace("\\", "/")
    
    # store the resolved path in the collate info for use in start/finish task
    collateInfo["info"]["resolvedPath"] = thisItemResolvedExportPath
    
    # Get the source start/end for this item
    sourceStart, sourceEnd = self._getSourceStartEndForItem(item.source(), item)
    collateInfo["info"]["sourceStart"] = sourceStart
    collateInfo["info"]["sourceEnd"] = sourceEnd
    
    # Get the timeline start/end for this item and the parent item.
    # We'll use this to offset secondary tracks' start frame if needed.
    timelineStart = item.timelineIn()
    parentTimelineStart = parentItem.timelineIn() if parentItem else timelineStart
    frameOffsetFromParentItemStart = timelineStart - parentTimelineStart

    srcPath = hiero.core.util.HashesToPrintf(item.source().mediaSource().fileinfos()[0].filename())
    dstPath = hiero.core.util.HashesToPrintf(thisItemResolvedExportPath)
    
    # Determine the offset between the source frame and the timeline frame.
    # This takes custom start frame(e.g. 1001) into account.
    # It also needs to be relative to the parentItem start frame if given.
    dstFrameOffset = (self._startFrame - sourceStart if self._startFrame is not None else 0) + frameOffsetFromParentItemStart
    for srcFrame in range(sourceStart, sourceEnd+1):
      srcFramePath = srcPath % srcFrame
      dstFrame = srcFrame + dstFrameOffset
      dstFramePath = self.formatFrameNumbers(dstPath, dstFrame, 1)
      self._paths.append( (srcFramePath, dstFramePath) )
      
    # store the targetStart/end. 
    collateInfo["info"]["targetStart"] = sourceStart + dstFrameOffset
    collateInfo["info"]["targetEnd"] = sourceEnd + dstFrameOffset
    
  def _getSourceStartEndForItem(self, clip, item):
    sourceStart = clip.sourceIn()
    sourceEnd = clip.sourceOut()
    
    # If exporting just the cut
    if self._cutHandles is not None:
      handles = self._cutHandles

      if self._retime:
        # Compensate for retime
        handles *= abs(item.playbackSpeed())

      # Ensure _start <= _end (for negative retimes, sourceIn > sourceOut)
      sourceInOut = (item.sourceIn(), item.sourceOut())
      sourceStart = min(sourceInOut)
      sourceEnd = max(sourceInOut)

      # This accounts for clips which do not start at frame 0 (e.g. dpx sequence starting at frame number 30)
      # We offset the TrackItem's in/out by clip's start frame.
      sourceStart += clip.sourceIn()
      sourceEnd += clip.sourceIn()

      # Add Handles
      sourceStart = max(sourceStart - handles, clip.sourceIn())
      sourceEnd   = min(sourceEnd + handles, clip.sourceOut())

    # Make sure values are integers
    sourceStart = int(math.floor(sourceStart))
    sourceEnd = int(math.ceil(sourceEnd))
    
    return sourceStart, sourceEnd

  def nothingToDo(self):
    return len(self._paths) == 0

  def startTask(self):
    pass

  def preFrame(self, src, dst):
    pass

  def doFrame(self, src, dst):
    pass
      
  def postFrame(self, src, dst):
    pass

  def formatFrameNumbers(self, string, frame, count=None):
    """Recursively split a string and modify with the % operation to replace the frame index.\n"""
    """@param count is the maximum number of replaces to do"""
    pos = string.rfind("%")
    if pos != -1 and (count > 0 or count is None):
      return self.formatFrameNumbers( string[:pos], frame, count -1) + string[pos:] % (frame, )
    return string

  def taskStep(self):
    FnShotExporter.ShotTask.taskStep(self)

    if self._currentPathIndex < len(self._paths):
      srcPath, dstPath = self._paths[self._currentPathIndex]
      self.preFrame(srcPath, dstPath)
      self.doFrame(srcPath, dstPath)
      self.postFrame(srcPath, dstPath)
      self._currentPathIndex += 1
      return True
    else:
      return False
    
  def progress(self):
    if self.nothingToDo():
      return 1.0
    return float(self._currentPathIndex) / float(len(self._paths))
