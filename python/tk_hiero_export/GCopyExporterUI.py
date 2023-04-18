import os.path

import hiero.ui
from . import GCopyExporter


class GCopyExporterUI(hiero.ui.TaskUIBase):
  def __init__(self, preset):
    """Initialize"""
    hiero.ui.TaskUIBase.__init__(self, GCopyExporter.GCopyExporter, preset, "Custom Copy Exporter")


hiero.ui.taskUIRegistry.registerTaskUI(GCopyExporter.GCopyPreset, GCopyExporterUI)
