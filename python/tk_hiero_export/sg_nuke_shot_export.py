# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import re
import os
import sys
import ast
import json
import shutil

from hiero.core import nuke
from hiero.exporters import FnNukeShotExporter
from hiero.exporters import FnNukeShotExporterUI

import sgtk
from sgtk.platform.qt import QtGui, QtCore

from .base import ShotgunHieroObjectBase
from . import HieroGetExtraPublishData

from .helpers import Collate, ResolveHelpers

class ShotgunNukeShotExporterUI(
    ShotgunHieroObjectBase, FnNukeShotExporterUI.NukeShotExporterUI
):
    """
    Custom Preferences UI for the shotgun nuke shot exporter
    """

    def __init__(self, preset):
        FnNukeShotExporterUI.NukeShotExporterUI.__init__(self, preset)
        self._displayName = "SG Nuke Project File"
        self._taskType = ShotgunNukeShotExporter

    def populateUI(self, widget, exportTemplate):
        FnNukeShotExporterUI.NukeShotExporterUI.populateUI(self, widget, exportTemplate)

        layout = widget.layout()
        self._toolkit_list = QtGui.QListView()
        self._toolkit_list.setMinimumHeight(50)
        self._toolkit_list.resize(200, 50)

        self._toolkit_model = QtGui.QStandardItemModel()
        nodes = self.app.get_setting("nuke_script_toolkit_write_nodes")
        properties = self._preset.properties()

        for node in nodes:
            name = 'Toolkit Node: %s ("%s")' % (node["name"], node["channel"])
            item = QtGui.QStandardItem(name)
            item.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
            if name in properties["toolkitWriteNodes"]:
                item.setData(QtCore.Qt.Checked, QtCore.Qt.CheckStateRole)
            else:
                item.setData(QtCore.Qt.Unchecked, QtCore.Qt.CheckStateRole)
            self._toolkit_model.appendRow(item)

        self._toolkit_list.setModel(self._toolkit_model)
        self._toolkit_model.dataChanged.connect(self.toolkitPresetChanged)

        form_layout = None

        # The layout type changed in 10.5v1. Prior to 10.5v1, the widget's
        # layout was a QFormLayout. Post 10.5v1, the layout is a QVBoxLayout
        # that contains a form layout where the UI should be inserted.
        if self.app.get_nuke_version_tuple() >= (10, 5, 1):
            # QVBoxLayout. Find the QFormLayout within. we'll assume it is the
            # first one we find.
            for child in layout.children():
                if isinstance(child, QtGui.QFormLayout):
                    # found a form layout
                    form_layout = child
                    break
        else:
            form_layout = layout

        if form_layout:
            form_layout.insertRow(0, "SG Write Nodes:", self._toolkit_list)
        else:
            self.app.log_error(
                "Unable to find the expected UI layout to display the list of "
                "SG Write Nodes in the export dialog."
            )

        # Handle any custom widget work the user did via the custom_export_ui
        # hook.
        custom_widget = self._get_custom_widget(
            parent=widget,
            create_method="create_nuke_shot_exporter_widget",
            get_method="get_nuke_shot_exporter_ui_properties",
            set_method="set_nuke_shot_exporter_ui_properties",
        )

        if custom_widget is not None:
            layout.addWidget(custom_widget)

    def toolkitPresetChanged(self, topLeft, bottomRight):
        self._preset.properties()["toolkitWriteNodes"] = []
        preset = self._preset.properties()["toolkitWriteNodes"]
        for row in range(0, self._toolkit_model.rowCount()):
            item = self._toolkit_model.item(row, 0)
            if item.data(QtCore.Qt.CheckStateRole) == QtCore.Qt.Checked:
                preset.append(item.text())

        self.app.log_debug("toolkitPresetChanged: %s" % preset)


class ShotgunNukeShotExporter(
    ShotgunHieroObjectBase, FnNukeShotExporter.NukeShotExporter
):
    """
    Create Transcode object and send to Shotgun
    """

    def __init__(self, initDict):
        """
        Constructor
        """
        FnNukeShotExporter.NukeShotExporter.__init__(self, initDict)
        self._resolved_export_path = None
        self._tk_version_number = None
        self._thumbnail = None
        self._hero = None
        self._heroItem = None


    def sequenceName(self):
        # override getSequence from the resolver to be collate friendly
        if getattr(self, "_collate", False):
            return self._item.parentSequence().name()
        return FnNukeShotExporter.NukeShotExporter.sequenceName(self)

    def taskStep(self):
        """
        Run Task
        """
        if self._resolved_export_path is None:
            self._resolved_export_path = self.resolvedExportPath()
            self._tk_version_number = self._formatTkVersionString(self.versionString())

            # convert slashes to native os style..
            self._resolved_export_path = self._resolved_export_path.replace(
                "/", os.path.sep
            )

        source = self._item.source()
        self._thumbnail = source.thumbnail(source.posterFrame())

        return FnNukeShotExporter.NukeShotExporter.taskStep(self)

    def startTask(self):
        """Run Task"""
        # call the publish data hook to allow for publish customization while _item is valid (unlike finishTask)
        self._extra_publish_data = self.app.execute_hook(
            "hook_get_extra_publish_data",
            task=self,
            base_class=HieroGetExtraPublishData,
        )

        return FnNukeShotExporter.NukeShotExporter.startTask(self)

    def finishTask(self):
        """
        Finish Task
        """
        # run base class implementation
        FnNukeShotExporter.NukeShotExporter.finishTask(self)

        # register publish
        # get context we're publishing to
        ctx = self.app.tank.context_from_path(self._resolved_export_path)
        published_file_type = self.app.get_setting("nuke_script_published_file_type")

        args = {
            "tk": self.app.tank,
            "context": ctx,
            "path": self._resolved_export_path,
            "name": os.path.basename(self._resolved_export_path),
            "version_number": int(self._tk_version_number),
            "published_file_type": published_file_type,
        }

        # see if we get a task to use
        if (ctx.entity is not None) and (ctx.entity.get("type", "") == "Shot"):
            try:
                task_filter = self.app.get_setting("default_task_filter", "[]")
                task_filter = ast.literal_eval(task_filter)
                task_filter.append(["entity", "is", ctx.entity])
                tasks = self.app.shotgun.find("Task", task_filter)
                if len(tasks) == 1:
                    args["task"] = tasks[0]
            except ValueError:
                # continue without task
                self.app.log_error("Invalid value for 'default_task_filter'")

        publish_entity_type = sgtk.util.get_published_file_entity_type(self.app.sgtk)

        self.app.log_debug("Register publish in ShotGrid: %s" % str(args))
        sg_publish = sgtk.util.register_publish(**args)
        if self._extra_publish_data is not None:
            self.app.log_debug(
                "Updating SG %s %s"
                % (publish_entity_type, str(self._extra_publish_data))
            )
            self.app.shotgun.update(
                sg_publish["type"], sg_publish["id"], self._extra_publish_data
            )

        # call the publish data hook to allow for publish customization.
        extra_publish_data = self.app.execute_hook(
            "hook_get_extra_publish_data",
            task=self,
            base_class=HieroGetExtraPublishData,
        )
        if extra_publish_data is not None:
            self.app.log_debug(
                "Updating SG %s %s" % (publish_entity_type, str(extra_publish_data))
            )
            self.app.shotgun.update(
                sg_publish["type"], sg_publish["id"], extra_publish_data
            )

        # upload thumbnail for sequence
        self._upload_thumbnail_to_sg(sg_publish, self._thumbnail)

        # Version Zero Generation
        # Get current script path and name
        scriptv1Path = self._resolved_export_path
        scriptv1Name = os.path.basename(scriptv1Path)
        # Only generate version zero from a v001
        if '.v001' in scriptv1Name:
            self.app.log_debug(f'Nuke Script v001 Path: {scriptv1Path}')
            # Generate script path and name for version zero
            scriptv0Path = scriptv1Path.replace('.v001.', '.v000.')
            scriptv0Name = os.path.basename(scriptv0Path)
            self.app.log_debug(f'Nuke Script v000 Path: {scriptv0Path}')
            
            #Modify file contents to update nuke root name to v000 and hiero metadata script path tag to v000
            # Read the nuke v001 script
            with open(scriptv1Path, "r") as file:
                nukeScriptv1Data = file.read()
                self.app.log_debug(f'Reading data from: {scriptv1Name}')

            # Swap out any paths inside the nuke script
            nukeScriptv0Data = nukeScriptv1Data.replace(scriptv1Name, scriptv0Name)

            # Write the modified data to a version zero script.
            with open(scriptv0Path, "w") as file:
                file.write(nukeScriptv0Data)
                self.app.log_debug(f'Writing data to: {scriptv0Name}')
            
                self.app.log_debug("Version Zero Sucessful!")
            
            # Publish v000
            # Tweak to already establshed args to reflect v000
            args['version_number'] = 000
            args['path'] = scriptv0Path
            args['name'] = scriptv0Name

            self.app.log_debug("Register publish in ShotGrid: %s" % str(args))
            sg_publish = sgtk.util.register_publish(**args)
            if self._extra_publish_data is not None:
                self.app.log_debug(
                    "Updating SG %s %s"
                    % (publish_entity_type, str(self._extra_publish_data))
                )
                self.app.shotgun.update(
                    sg_publish["type"], sg_publish["id"], self._extra_publish_data
                )
            # call the publish data hook to allow for publish customization.
            extra_publish_data = self.app.execute_hook(
                "hook_get_extra_publish_data",
                task=self,
                base_class=HieroGetExtraPublishData,
            )
            if extra_publish_data is not None:
                self.app.log_debug(
                    "Updating SG %s %s" % (publish_entity_type, str(extra_publish_data))
                )
                self.app.shotgun.update(
                    sg_publish["type"], sg_publish["id"], extra_publish_data
                )

            # upload thumbnail for sequence
            self._upload_thumbnail_to_sg(sg_publish, self._thumbnail)
            
        else:
            self.app.log_error("Version Zero Generation Skipped - Nuke script not v001")

        # Log usage metrics
        try:
            self.app.log_metric("Shot Export", log_version=True)
        except:
            # ingore any errors. ex: metrics logging not supported
            pass

    def isExportingItem(self, item):
        """
        This method overrides the default method added to the base class in
        Nuke 10. The base class returns ``True`` for all items found in the
        list of collated items. This prevents unnecessary exports for those items
        since non-SG workflows only collate into the exported nuke script of the
        first exported track item. For SG workflows, we still export versions
        for collated tracks and link them back to the hero shot. So we need to
        do our own culling of tasks in the shot processor. So we return ``False``
        unless the item is the current item.
        """

        # Return true if this is the main item for this task, or it's in the list of collated items.
        if item == self._item:
            return True
        else:
            return False

    def _beforeNukeScriptWrite(self, script):
        """
        Add ShotgunWriteNodePlaceholder Metadata nodes for tk-nuke-writenode to
        create full Tk WriteNodes in the Nuke environment
        """
        FnNukeShotExporter.NukeShotExporter._beforeNukeScriptWrite(self, script)

        # As the default script from Nuke Studio 11 > has a viewer node as the last node, it means that we
        # can't simply relying on our write nodes being linked up at the end. Instead we need to manually modify
        # the script by temporarily removing the viewer node and then adding it back in.
        nodeList = script.getNodes()

        currentLayoutContext = script._layoutContextStack[-1]

        # extract the current end Node from the script but keep hold of it so we can add it back on.
        oldScriptEnd = nodeList.pop()

        # now extract the last node's layout and keep hold of it so we can add it back on.
        oldLayoutEnd = currentLayoutContext.getNodes().pop()

        try:
            for toolkit_specifier in self._preset.properties()["toolkitWriteNodes"]:
                # break down a string like 'Toolkit Node: Mono Dpx ("editorial")' into name and output
                match = re.match(
                    '^Toolkit Node: (?P<name>.+) \("(?P<output>.+)"\)',
                    toolkit_specifier,
                )

                metadata = match.groupdict()
                node = nuke.MetadataNode(metadatavalues=list(metadata.items()))
                node.setName("ShotgunWriteNodePlaceholder")

                self.app.log_debug(
                    "Created ShotgunWriteNodePlaceholder Node: %s" % node._knobValues
                )
                # rather than using the script.addNode, we append our node directly to the nodeList
                nodeList.append(node)

                # now add our new node to the layout
                currentLayoutContext.getNodes().append(node)
        except Exception:
            self.app.logger.exception("Failed to add SG writenodes")
        finally:
            # now put back the viewer nodes layout
            currentLayoutContext.getNodes().append(oldLayoutEnd)

            # put the old end Node back
            nodeList.append(oldScriptEnd)
            
        # Add any collated plates here
        self._addCollatedPlatesToScript(nodeList)
        
        
    def _addCollatedPlatesToScript(self, nodeList):
        
        # in the GCollatedFrameExporter we previously populated and stored collate info 
        # for this track item in the os env, which is obviously terrible, but very helpful!
        # lets pull it out of the env here in order to find our collated track items
        envKey = "HIERO_COLLATE_INFO_{}".format(self._item.guid())
        if not os.environ.get(envKey, None):
            print("Could not find collated track info")
            return
        
        shotCollateInfo = json.loads(os.environ.get(envKey))
        if len(shotCollateInfo["overlappingItems"]) == 0:
            return
        
        # the main read node will be the only read node in the script. ensure it also has it's first/last values set
        # NOTE: frustratingly these are internal node representations only so knob values aren't subscriptable
        mainRead = next((n for n in nodeList if "ReadNode" in str(n) and n.knobs().get("first", None) and n.knobs().get("last", None)), None)
        if not mainRead:
            print("Couldn't find main read")
            return
        
        # get the main plate in/out
        readIn = mainRead.knobs()["first"]
        readOut = mainRead.knobs()["last"]
        
        # loop through all overlapping items
        # only add each resolved path once
        addedPaths = []
        for collateInfo in shotCollateInfo["overlappingItems"]:
            
            # get the resolved path
            resolvedPath = collateInfo["info"]["resolvedPath"]
            
            # if we've already added this seq, continue
            if resolvedPath in addedPaths:
                continue
            
            # TODO: set position in nuke script and backdrop
            # Make a read node with that path
            newRead = nuke.ReadNode(resolvedPath)
            
            # Set the in/out to match the main plate
            newRead.setKnob("first", readIn)
            newRead.setKnob("last", readOut)
            newRead.setKnob("origfirst", readIn)
            newRead.setKnob("origlast", readOut)
            
            # set the error to black frame
            newRead.setKnob("on_error", "black")
            
            # add to the node list
            nodeList.append(newRead)
            
            # store the resolved path so we only add that seq once
            addedPaths.append(resolvedPath)


class ShotgunNukeShotPreset(
    ShotgunHieroObjectBase, FnNukeShotExporter.NukeShotPreset
):
    """
    Settings for the shotgun transcode step
    """

    #TODO MB: Does this need updating?
    def __init__(self, name, properties):
        FnNukeShotExporter.NukeShotPreset.__init__(self, name, properties)
        self._parentType = ShotgunNukeShotExporter

        if "toolkitWriteNodes" in properties:
            # already taken care of by loading the preset
            return

        # default toolkit write nodes
        toolkit_write_nodes = []
        nodes = self.app.get_setting("nuke_script_toolkit_write_nodes")
        for node in nodes:
            name = 'Toolkit Node: %s ("%s")' % (node["name"], node["channel"])
            toolkit_write_nodes.append(name)
        self.properties()["toolkitWriteNodes"] = toolkit_write_nodes

        # Handle custom properties from the customize_export_ui hook.
        custom_properties = (
            self._get_custom_properties("get_nuke_shot_exporter_ui_properties") or []
        )

        self.properties().update({d["name"]: d["value"] for d in custom_properties})
