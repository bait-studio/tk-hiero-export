# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import os.path
import ast
import sys
import time
import shutil

from . import GCollatedFrameExporter
import hiero.ui

import hiero
from hiero import core
from hiero.core import *
import hiero.core
from hiero.core import util
import hiero.core.nuke as nuke

import tank
import sgtk.util
from sgtk.platform.qt import QtGui, QtCore

from .base import ShotgunHieroObjectBase

from . import (
    HieroGetShot,
    HieroUpdateVersionData,
    HieroPostVersionCreation,
)

from .helpers import TaskHelpers

class ShotgunCopyExporterUI(
    ShotgunHieroObjectBase, hiero.ui.TaskUIBase
):
    """
    Custom Preferences UI for the shotgun copy exporter

    Embeds the UI for the std copy UI.
    """

    def __init__(self, preset):
        hiero.ui.TaskUIBase.__init__(self, GCollatedFrameExporter.GCollatedFrameExporter, preset, "Custom Copy Exporter")
        self._displayName = "SG Copy Files"
        self._taskType = ShotgunCopyExporter

    def create_version_changed(self, state):
        create_version = state == QtCore.Qt.Checked
        self._preset._properties["create_version"] = create_version

    def populateUI(self, widget, exportTemplate):

        # prior to 10.5v1, this method created the layout. in 10.5v1 and later,
        # the widget already has a layout
        if self.app.get_nuke_version_tuple() >= (10, 5, 1):
            layout = widget.layout()
        else:
            # create a layout with custom top and bottom widgets
            layout = QtGui.QVBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(9)

        #Customise layout here if needed

        # prior to 10.5v1, the layout was set in the base class. in 10.5v1, the
        # base class expects the widget to already have a layout.
        middle = QtGui.QWidget()
        if self.app.get_nuke_version_tuple() >= (10, 5, 1):
            middle.setLayout(QtGui.QVBoxLayout())

        # populate the middle with the standard layout
        hiero.ui.TaskUIBase.populateUI(
            self, middle, exportTemplate
        )

        layout.addWidget(middle)

        # Handle any custom widget work the user did via the custom_export_ui
        # hook.
        custom_widget = self._get_custom_widget(
            parent=widget,
            create_method="create_sg_exporter_widget",
            get_method="get_sg_exporter_ui_properties",
            set_method="set_sg_exporter_ui_properties",
        )

        if custom_widget is not None:
            layout.addWidget(custom_widget)


class ShotgunCopyExporter(
    ShotgunHieroObjectBase, GCollatedFrameExporter.GCollatedFrameExporter
):
    """
    Custom exporter that includes functionality from the FnCopyExporter and FnFrameExporter.
    It does this so we can completely control collated plate copying during the copy task.
    """

    def __init__(self, initDict):
        """Constructor"""

        # CopyExporter
        GCollatedFrameExporter.GCollatedFrameExporter.__init__( self, initDict )
        
        if self.nothingToDo():
            return
  
        self._resolved_export_path = None
        self._sequence_name = None
        self._shot_name = None
        self._thumbnail = None

    def startTask(self):
        """Run Task"""
        if self._resolved_export_path is None:
            self._resolved_export_path = self.resolvedExportPath()
            self._tk_version = self._formatTkVersionString(self.versionString())
            self._sequence_name = self.sequenceName()

            # convert slashes to native os style..
            self._resolved_export_path = self._resolved_export_path.replace(
                "/", os.path.sep
            )

        # call the get_shot hook
        ########################
        if self.app.shot_count == 0:
            self.app.preprocess_data = {}

        # associate publishes with correct shot, which will be the hero item
        # if we are collating
        item = self._item

        # store the shot for use in finishTask. query the head/tail values set
        # on the shot updater task so that we can set those values on the
        # Version created later.
        self._sg_shot = self.app.execute_hook(
            "hook_get_shot",
            task=self,
            item=item,
            data=self.app.preprocess_data,
            fields=["sg_head_in", "sg_tail_out"],
            base_class=HieroGetShot,
        )

        # populate the data dictionary for our Version while the item is still valid
        ##############################
        # see if we get a task to use
        self._sg_task = None
        try:
            task_filter = self.app.get_setting("default_task_filter", "[]")
            task_filter = ast.literal_eval(task_filter)
            task_filter.append(["entity", "is", self._sg_shot])
            tasks = self.app.shotgun.find("Task", task_filter)
            if len(tasks) == 1:
                self._sg_task = tasks[0]
        except ValueError:
            # continue without task
            setting = self.app.get_setting("default_task_filter", "[]")
            self.app.log_error("Invalid value for 'default_task_filter': %s" % setting)

        if self._preset.properties()["create_version"]:
            # lookup current login
            sg_current_user = tank.util.get_current_user(self.app.tank)

            file_name = os.path.basename(self._resolved_export_path)
            file_name = os.path.splitext(file_name)[0]
            file_name = file_name.capitalize()

            # use the head/tail to populate frame first/last/range fields on
            # the Version
            head_in = self._sg_shot["sg_head_in"]
            tail_out = self._sg_shot["sg_tail_out"]

            self._version_data = {
                "user": sg_current_user,
                "created_by": sg_current_user,
                "entity": self._sg_shot,
                "project": self.app.context.project,
                "sg_path_to_frames": self._resolved_export_path,
                "code": file_name,
                "sg_first_frame": head_in,
                "sg_last_frame": tail_out,
                "frame_range": "%s-%s" % (head_in, tail_out),
            }

            if self._sg_task is not None:
                self._version_data["sg_task"] = self._sg_task

            # call the update version hook to allow for customization
            self.app.execute_hook(
                "hook_update_version_data",
                version_data=self._version_data,
                task=self,
                base_class=HieroUpdateVersionData,
            )

        # figure out the thumbnail frame
        ##########################
        source = self._item.source()

        # If we can't get a thumbnail it isn't the end of the world.
        # When we get to the upload we'll do nothing if we don't have
        # anything to work with, which will result in the same result
        # as if the thumbnail failed to upload.
        try:
            self._thumbnail = source.thumbnail(self._item.sourceIn())
            # thumb.save("C:/Users/matt.brealey/Desktop/thumb.png", "PNG", -1)
        except Exception:
            pass

        return GCollatedFrameExporter.GCollatedFrameExporter.startTask(self)

    def finishTask(self):
        """Finish Task"""
        # run base class implementation
        GCollatedFrameExporter.GCollatedFrameExporter.finishTask(self)

        # create publish
        ################
        # by using entity instead of export path to get context, this ensures
        # collated plates get linked to the hero shot
        ctx = self.app.tank.context_from_entity("Shot", self._sg_shot["id"])
        published_file_type = self.app.get_setting("plate_published_file_type")

        args = {
            "tk": self.app.tank,
            "context": ctx,
            "path": self._resolved_export_path,
            "name": os.path.basename(self._resolved_export_path),
            "version_number": int(self._tk_version),
            "published_file_type": published_file_type,
        }

        if self._sg_task is not None:
            args["task"] = self._sg_task

        published_file_entity_type = sgtk.util.get_published_file_entity_type(
            self.app.sgtk
        )

        # register publish
        self.app.log_debug("Register publish in shotgun: %s" % str(args))
        pub_data = tank.util.register_publish(**args)

        # upload thumbnail for publish
        if self._thumbnail:
            self._upload_thumbnail_to_sg(pub_data, self._thumbnail)

        # create version
        ################
        vers = None
        if self._preset.properties()["create_version"]:
            if published_file_entity_type == "PublishedFile":
                self._version_data["published_files"] = [pub_data]
            else:  # == "TankPublishedFile
                self._version_data["tank_published_file"] = pub_data

            self.app.log_debug("Creating SG Version %s" % str(self._version_data))
            vers = self.app.shotgun.create("Version", self._version_data)

        # Post creation hook
        ####################
        if vers:
            self.app.execute_hook(
                "hook_post_version_creation",
                version_data=vers,
                base_class=HieroPostVersionCreation,
            )

        # Web-reviewable media creation
        ####################
        if vers:
            TaskHelpers.createWebReviewable(self, vers)
    
    def _tryCopy(self,src, dst):
        """Attempts to copy src file to dst, including the permission bits, last access time, last modification time, and flags"""

        hiero.core.log.info("Attempting to copy %s to %s" % (src, dst))
        
        try:
            shutil.copy2(util.asUnicode(src), util.asUnicode(dst))
        except shutil.Error as e:
            # Dont need to report this as an error
            if e.message.endswith("are the same file"):
                pass
            else:
                self.setError("Unable to copy file. %s" % e.message)
        except OSError as err:
            # If the OS returns an ENOTSUP error (45), for example when trying to set
            # flags on an NFS mounted volume that doesn't support them, Python should
            # absorb this.  However, a regression in Python 2.7.3 causes this not to
            # be the case, and the error is thrown as an exception.  We therefore
            # catch this explicitly as value 45, since errno.ENOTSUP is not defined
            # in Python 2.7.2 (which is part of the problem).  See the following
            # link for further information: http://bugs.python.org/issue14662
            # See TP 199072.
            if err.errno == 45: # ENOTSUP
                pass
            else:
                raise

    def doFrame(self, src, dst):
        hiero.core.log.info( "SG_Copy_Exporter. DoFrame" )
        hiero.core.log.info( "  - source: " + str(src) )
        hiero.core.log.info( "  - destination: " + str(dst) )

        # Find the base destination directory, if it doesn't exist create it
        dstdir = os.path.dirname(dst)
        util.filesystem.makeDirs(dstdir)

        # Copy file including the permission bits, last access time, last modification time, and flags
        self._tryCopy(src, dst)

class ShotgunCopyPreset(
    ShotgunHieroObjectBase, hiero.core.TaskPresetBase
):
    """Settings for the SG copy step"""

    def __init__(self, name, properties):
        hiero.core.TaskPresetBase.__init__(self, GCollatedFrameExporter, name)
        self._parentType = ShotgunCopyExporter

        # set default values
        self.properties().update(properties)
        self._properties["create_version"] = True

        # Handle custom properties from the customize_export_ui hook.
        custom_properties = (
            self._get_custom_properties("get_sg_exporter_ui_properties") or []
        )

        self.properties().update({d["name"]: d["value"] for d in custom_properties})
        
    def supportedItems(self):
        return hiero.core.TaskPresetBase.kTrackItem
