import hiero 

#Get Hiero Items
def _getProject(projectName):
  for project in hiero.core.projects():
    if project.name() == projectName:
      return project
  return None

def _getSequence(project, sequenceName):
  for sequence in project.sequences():
    if sequence.name() == sequenceName:
      return sequence
  return None

def _getVideoTrack(sequence, trackName):
  for track in sequence.videoTracks():
    if track.name() == trackName:
      return track
  return None

#Get collate info for a single track item
def _getOverlappingItemsForTrackItem(trackItem, allOtherItems):
  #Find all items that overlap track item
  start = trackItem.timelineIn()
  end = trackItem.timelineOut()

  overlappingItems = []
  for item in allOtherItems:
    #Item overlaps if :
    # 1. It is completely contained within/exactly equal to the main track item
    # 2. It starts before, but ends during or at the same point.
    # 3. It starts during or at the same point, and ends after or at same point.
    # 4. It starts before, and ends after.

    #Could simplify this code, but lets keep this explicit during initial testing.
    otherStart = item.timelineIn()
    otherEnd = item.timelineOut()

    #1.
    if otherStart >= start and otherEnd <= end:
      overlappingItems.append(item)
      #print("\t{} is contained within/the same as. {}-{} {}-{}".format(item, start, end, otherStart, otherEnd))

    #2.
    elif otherStart < start and otherEnd > start and otherEnd <= end:
      overlappingItems.append(item)
      #print("\t{} starts before, but ends during or at the same point. {}-{} {}-{}".format(item, start, end, otherStart, otherEnd))

    #3. 
    elif otherStart >= start and otherStart < end and otherEnd >= end:
      overlappingItems.append(item)
      #print("\t{} starts during or at same point and ends after or at same point. {}-{} {}-{}".format(item, start, end, otherStart, otherEnd))

    #4. 
    elif otherStart < start and otherEnd > end:
      overlappingItems.append(item)
      #print("\t{} starts before and ends after. {}-{} {}-{}".format(item, start, end, otherStart, otherEnd))

  #Return collate info
  return overlappingItems

#Safely wrapped get collate info func. We know all items exist at this point.
def _getCollateInfo(sequence, track):

  #Store the info, by main track item guid
  collateInfo = {}
  print("")

  #Get the main track items
  mainTrackItems = track.items()

  #Get all other track items
  allOtherTrackItems = [y for x in sequence.videoTracks() for y in x.items()  if x.guid() != track.guid()]

  #For each of the main track items, get the collate info and store
  for mainTrackItem in mainTrackItems:
    collateInfo[mainTrackItem.guid()] = {
      "item": mainTrackItem,
      "overlappingItems": _getOverlappingItemsForTrackItem(mainTrackItem, allOtherTrackItems)
    }

  return collateInfo


def getCollateInfo(projectName, sequenceName, mainTrackName):
  #Get the elements we need to do the lookup - project, sequence and track
  project = _getProject(projectName)
  if not project:
    print("No project found with name '{}'".format(projectName))
    return None

  sequence = _getSequence(project, sequenceName)
  if not sequence:
    print("No sequence found with name '{}' in project '{}'".format(sequenceName, projectName))
    return None

  mainTrack = _getVideoTrack(sequence, mainTrackName)
  if not mainTrack:
    print("No track found with name '{}' in sequence '{}' in project '{}'".format(mainTrackName, sequenceName, projectName))
    return None

  #Return the info for the given track in the given sequence
  return _getCollateInfo(sequence, mainTrack)

#Determine the collate info for the given test track
collateInfo = getCollateInfo("MattTest_v001", "HS2", "Video 1")
for itemID in collateInfo:
  print("{} has {} overlapping items".format(collateInfo[itemID]["item"], len(collateInfo[itemID]["overlappingItems"])))