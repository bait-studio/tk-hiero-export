# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
Update the Hiero export to be Tank/Shotgun aware
"""
import re
import os
import sys
import shutil
import tempfile
import traceback

import sgtk
from sgtk.platform.qt import QtCore
from sgtk.platform import Application
from sgtk import TankError

import hiero.ui
import hiero.core
import hiero.exporters

from hiero.exporters import FnExternalRender
from hiero.exporters import FnNukeShotExporter

# do not use tk import here, hiero needs the classes to be in their
# standard namespace, hack to get the right path in sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), "python"))

from tk_hiero_export import (
    ShotgunShotProcessor,
    ShotgunShotProcessorUI,
    ShotgunShotUpdater,
    ShotgunCopyPreset,
    ShotgunSymLinkPreset,
    ShotgunTranscodePreset,
    ShotgunNukeShotPreset,
    ShotgunAudioPreset,
    ShotgunShotUpdaterPreset,
    ShotgunCopyExporter,
    ShotgunSymLinkExporter,
    ShotgunTranscodeExporter,
    ShotgunNukeShotExporter,
    ShotgunAudioExporter,
    ShotgunShotProcessorPreset,
    ShotgunCopyExporterUI,
    ShotgunSymLinkExporterUI,
    ShotgunTranscodeExporterUI,
    ShotgunNukeShotExporterUI,
    ShotgunAudioExporterUI,
    ShotgunHieroObjectBase,
)

sys.path.pop()

# list keywords Hiero is using in its export substitution
HIERO_SUBSTITUTION_KEYWORDS = [
    "clip",
    "day",
    "DD",
    "event",
    "ext",
    "filebase",
    "fileext",
    "filehead",
    "filename",
    "filepadding",
    "fullbinpath",
    "fullday",
    "fullmonth",
    "MM",
    "month",
    "project",
    "projectroot",
    "sequence",
    "shot",
    "step",
    "tk_version",
    "track",
    "user",
    "version",
    "YY",
    "YYYY",
]


class HieroExport(Application):
    def init_app(self):
        # let the shot exporter know when the first shot is being run
        self.first_shot = False
        self._register_exporter()

    @property
    def context_change_allowed(self):
        """
        Specifies that context changes are allowed.
        """
        return True

    def get_default_encoder_name(self):
        """Returns the default encoder for use in quicktime generation.

        The value returned is dependent on the platform and the version of
        Hiero/NukeStudio being used.

        The "mov32" encoder does not work in newer versions of Hiero/NukeStudio
        (10.0v2 or greater) where there is no dependency on the Qt desktop
        application.

        :return: The name of the default encoder to use for this platform
            and version of Hiero/NukeStudio
        :rtype: str
        """

        if sgtk.util.is_linux():
            encoder_name = "mov64"
        else:
            encoder_name = "mov32"
            try:
                import nuke

                if nuke.NUKE_VERSION_MAJOR >= 10 and nuke.NUKE_VERSION_RELEASE > 1:
                    # newer version of nuke without access to desktop Qt
                    encoder_name = "mov64"
            except ImportError:
                # can't import nuke. older version of Hiero
                pass

        return encoder_name

    def get_nuke_version_tuple(self):
        """
        Returns a tuple of the nuke version for comparing against using python's
        handy tuple comparison.

        Usage example::

            # see if the current version is >= Nuke 10.5v1
            if app.get_nuke_version_tuple() >= (10, 5, 1):
                ...
        """

        import nuke

        return (
            nuke.NUKE_VERSION_MAJOR,
            nuke.NUKE_VERSION_MINOR,
            nuke.NUKE_VERSION_RELEASE,
        )

    def _register_exporter(self):
        """
        Set up this app with the hiero exporter frameworks
        """
        # register our app with the base class that all custom hiero objects derive from.
        ShotgunHieroObjectBase.setApp(self)

        hiero.core.taskRegistry.registerTask(
            ShotgunShotUpdaterPreset, ShotgunShotUpdater
        )
        hiero.core.taskRegistry.registerTask(
            ShotgunCopyPreset, ShotgunCopyExporter
        )
        hiero.core.taskRegistry.registerTask(
            ShotgunSymLinkPreset, ShotgunSymLinkExporter
        )
        hiero.core.taskRegistry.registerTask(
            ShotgunTranscodePreset, ShotgunTranscodeExporter
        )
        hiero.core.taskRegistry.registerTask(
            ShotgunNukeShotPreset, ShotgunNukeShotExporter
        )
        hiero.core.taskRegistry.registerTask(ShotgunAudioPreset, ShotgunAudioExporter)
        hiero.core.taskRegistry.registerProcessor(
            ShotgunShotProcessorPreset, ShotgunShotProcessor
        )

        hiero.ui.taskUIRegistry.registerTaskUI(
            ShotgunCopyPreset, ShotgunCopyExporterUI
        )
        hiero.ui.taskUIRegistry.registerTaskUI(
            ShotgunSymLinkPreset, ShotgunSymLinkExporterUI
        )
        hiero.ui.taskUIRegistry.registerTaskUI(
            ShotgunTranscodePreset, ShotgunTranscodeExporterUI
        )
        hiero.ui.taskUIRegistry.registerTaskUI(
            ShotgunNukeShotPreset, ShotgunNukeShotExporterUI
        )
        hiero.ui.taskUIRegistry.registerTaskUI(
            ShotgunAudioPreset, ShotgunAudioExporterUI
        )
        hiero.ui.taskUIRegistry.registerProcessorUI(
            ShotgunShotProcessorPreset, ShotgunShotProcessorUI
        )

        # Add our default preset
        self._old_AddDefaultPresets_fn = hiero.core.taskRegistry._defaultPresets
        hiero.core.taskRegistry.setDefaultPresets(self._add_default_presets)

    def _add_default_presets(self, overwrite):
        """
        Hiero std method to add new exporter presets.
        Passed in to hiero.core.taskRegistry.setDefaultPresets() as a function pointer.
        """
        # add all built-in defaults
        self._old_AddDefaultPresets_fn(overwrite)

        # add custom dynamic export preset - always overwrite
        self._add_dynamic_export_preset(True)

    def _add_dynamic_export_preset(self, overwrite):
        # first step is to get the working format from the current project
        # Add Shotgun template
        name = "SG Export"
        localpresets = [
            preset.name() for preset in hiero.core.taskRegistry.localPresets()
        ]

        # only add the preset if it is not already there - or if a reset to defaults is requested.
        if overwrite or name not in localpresets:
            # grab all our path templates
            working_format = os.environ["SG_WORKING_FORMAT"].lower()
            plate_template = self.get_template("template_plate_path_{}".format(working_format))
            script_template = self.get_template("template_nuke_script_path")
            render_template = self.get_template("template_nuke_render_path_{}".format(working_format))


            # call the hook to translate them into hiero paths, using hiero keywords
            hiero_plate_template_string = self.execute_hook(
                "hook_translate_template", template=plate_template, output_type="plate"
            )

            nuke_script_template_string = self.execute_hook(
                "hook_translate_template",
                template=script_template,
                output_type="script",
            )

            nuke_render_template_string = self.execute_hook(
                "hook_translate_template",
                template=render_template,
                output_type="render",
            )

            # check so that no unknown keywords exist in the templates after translation
            self._validate_hiero_export_template(hiero_plate_template_string)
            self._validate_hiero_export_template(nuke_script_template_string)
            self._validate_hiero_export_template(nuke_render_template_string)

            # switch to linux slashes
            norm_hiero_plate_template_string = os.path.normpath(hiero_plate_template_string).replace(os.path.sep, "/")
            norm_nuke_script_template_string = os.path.normpath(nuke_script_template_string).replace(os.path.sep, "/")
            norm_nuke_render_template_string = os.path.normpath(nuke_render_template_string).replace(os.path.sep, "/")  
            # print(norm_hiero_plate_template_string)
            # print(norm_nuke_script_template_string)
            # print(norm_nuke_render_template_string)

            # get the format settings to use
            dpx_properties = self.get_setting("dpx_write_node_properties")
            exr_properties = self.get_setting("exr_write_node_properties")

            # generate the export template
            export_template = (
                    (
                        norm_hiero_plate_template_string,
                        ShotgunCopyPreset(
                            "", {}
                        ),
                    ),
                    (
                        norm_nuke_script_template_string,
                        ShotgunNukeShotPreset(
                            "", 
                            {
                                "readPaths": [norm_hiero_plate_template_string], 
                                "writePaths": [],
                                "toolkitWriteNodes": ['Toolkit Node: {} ("{}")'.format(working_format.upper(), working_format)]
                            }
                        ),
                    ),
                    (
                        norm_nuke_render_template_string,
                        FnExternalRender.NukeRenderPreset(
                            "", 
                            {
                                "file_type": working_format, 
                                "exr": exr_properties, 
                                "dpx": dpx_properties
                            }
                        ),
                    ),
                    
                )

            # and set the default properties to be based off of those templates
            properties = {
                "exportRoot": os.environ["SG_PROJECT_ROOT"],
                "exportTemplate": export_template,
                "cutLength": True,
                "startFrameIndex": 1001,
                "startFrameSource": "Custom",
                "cutHandles":8
            }
            preset = ShotgunShotProcessorPreset(name, properties)
            hiero.core.taskRegistry.removeProcessorPreset(name)
            hiero.core.taskRegistry.addProcessorPreset(name, preset)

            print("Added dynamic 'SG Export' template for project '{}' with working format '{}'.".format(os.environ["SG_PROJECT_NAME"], working_format))

    def _validate_hiero_export_template(self, template_str):
        """
        Validate that a template_str only contains Hiero substitution keywords or custom
        keywords created via the resolve_custom_strings hook.
        """
        # build list of valid tokens
        custom_substitution_keywords = [
            x["keyword"] for x in self.get_setting("custom_template_fields")
        ]
        valid_substitution_keywords = (
            HIERO_SUBSTITUTION_KEYWORDS + custom_substitution_keywords
        )
        hiero_resolver_tokens = ["{%s}" % x for x in valid_substitution_keywords]
        # replace all tokens we know about in the template
        for x in hiero_resolver_tokens:
            template_str = template_str.replace(x, "")

        # find any remaining {xyz} tokens in the template
        regex = r"(?<={)[a-zA-Z_ 0-9]+(?=})"
        key_names = re.findall(regex, template_str)
        if len(key_names) > 0:
            raise TankError(
                "The configuration template '%s' contains keywords %s which are "
                "not recognized by Hiero. Either remove them from the sgtk template "
                "or adjust the hook that converts a template to a hiero export "
                "path to convert these fields into fixed strings or hiero "
                "substitution tokens." % (template_str, ",".join(key_names))
            )
