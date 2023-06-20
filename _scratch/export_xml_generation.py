from xml.dom import minidom

EXPORTERS = {
  "sg_copy_exporter": {
    "preset": "tk_hiero_export.sg_copy_exporter.ShotgunCopyPreset",
    "exporter": "tk_hiero_export.sg_copy_exporter.ShotgunCopyExporter",
  },
  "sg_nuke_shot_export": {
    "preset": "tk_hiero_export.sg_nuke_shot_export.ShotgunNukeShotPreset",
    "exporter": "tk_hiero_export.sg_nuke_shot_export.ShotgunNukeShotExporter"
  },
  "FnExternalRender": {
    "preset": "hiero.exporters.FnExternalRender.NukeRenderPreset",
    "exporter": "hiero.exporters.FnExternalRender.NukeRenderTask"
  }
}

def _generateTemplateDict():
  return {
    "root": {
      "args":{
        "presetname":"SG Export",
        "tasktype":"tk_hiero_export.sg_shot_processor.ShotgunShotProcessor",
      },
      "excludeTags":[],
      "includeTags":[{
        "SequenceItem": "Blue"
      }],
      "versionIndex":1,
      "versionPadding":2,
      "exportTemplate":[],
      "exportRoot":"",
      "cutHandles":12,
      "cutUseHandles":False,
      "cutLength":True,
      "includeRetimes":False,
      "startFrameIndex":1001,
      "startFrameSource":"Custom",
      "shotgunShotCreateProperties":{}
    }
  }

def _createExportStructureItem(presetType, outputPath, data):
  item = {
    "SequenceItem": (
      {
        "SequenceItem":outputPath
      },
      {
        "SequenceItem":{
          "args":{
            "valuetype": EXPORTERS[presetType]["preset"],
          },
          "root":{
            "args":{
              "presetname": EXPORTERS[presetType]["preset"],
              "tasktype": EXPORTERS[presetType]["exporter"],
            },
          }
        }
      }
    )
  }
  for key in data:
    item["SequenceItem"][1]["SequenceItem"]["root"][key] = data[key]

  return item

def _getValueType(data):
  return str(type(data)).split("'")[1]

def _generateXMLNodesFromDict(data, parentNode=None, doc=None):
  #Top-most level will be ignored, but is used to contain all subsequent XML
  if not doc or not parentNode:
    doc = minidom.Document()
    parentNode = doc

  #Loop through dict structure, converting each key as we go and appending to the parent.
  #As of python 3.6, dict key order is maintained.
  for key in data:
    #Ignore processing args entries directly
    if key == "args":
      continue
    
    #Create a node for each key
    node = doc.createElement(key)
    
    #Set the value type
    node.setAttribute("valuetype", _getValueType(data[key]))

    #If this value is a dict, iterate over children
    if isinstance(data[key], dict):
      #If there is an args dict, add these attributes directly
      if data[key].get("args", None):
        #Add the arguments on the new node
        for arg, argValue in data[key]["args"].items():
          node.setAttribute(arg, argValue)

      #Process the other keys directly
      _generateXMLNodesFromDict(data[key], node, doc)

    #Else set the value type directly
    else:

      #Process children if value is a list
      if isinstance(data[key], list) or isinstance(data[key], tuple):
        for child in data[key]:
          _generateXMLNodesFromDict(child, node, doc)

      #Otherwise set node content
      else:
        content = str(data[key])
        if len(content):
          node.appendChild(doc.createTextNode(str(data[key])))

    #Append the child node
    parentNode.appendChild(node)

  return doc

def main():
  #Create the template dict
  dict = _generateTemplateDict()

  #Create export items
  #Main plate path
  exportItem1 = _createExportStructureItem(
    "sg_copy_exporter",
    "sequences/{sequence}/{shot}/{step}/editorial/plates/v{tk_version}/{shot}.####.{fileext}",
    {
      "collateTracks":False,
      "collateShotNames":False,
      "collateSequence":False,
      "collateCustomStart":False,
      "create_version":True,
    }
  )
  dict["root"]["exportTemplate"].append(exportItem1)

  #Comp
  exportItem2 = _createExportStructureItem(
    "sg_nuke_shot_export",
    "sequences/{sequence}/{shot}/{step}/work/nuke/{shot}_comp.v{tk_version}.{fileext}",
    {
      "readPaths":[
        {"SequenceItem":"sequences/{sequence}/{shot}/{step}/editorial/plates/v{tk_version}/{shot}.####.{fileext}"}
      ],
      "writePaths":[],
      "timelineWriteNode":"",
      "collateTracks":False,
      "collateShotNames":False,
      "collateSequence":False,
      "collateCustomStart":False,
      "connectTracks":False,
      "postProcessScript":True,
      "toolkitWriteNodes":[
        {"SequenceItem": 'Toolkit Node: EXR ("exr")'}
      ]
    }
  )
  dict["root"]["exportTemplate"].append(exportItem2)

  #Renders
  exportItem3 = _createExportStructureItem(
    "FnExternalRender",
    "sequences/{sequence}/{shot}/{step}/work/nuke/renders/v{tk_version}/{shot}_comp.####.{fileext}",
    {
      "file_type": "exr",
    }
  )
  dict["root"]["exportTemplate"].append(exportItem3)

  #Add Shotgrid properties
  # shotgridProperties = _createShotgridProperties()

  #Determine export root
  dict["root"]["exportRoot"] = "path/to/thing"

  #Convert to XML
  xml = _generateXMLNodesFromDict(dict)
  print(xml.toprettyxml(indent ="\t"))

  #Write
  outputPath = "c:/Users/Tom.tatchell/Desktop/SG_Export.xml"
  with open(outputPath, "w") as xmlFile:
    xml.writexml(xmlFile)

main()