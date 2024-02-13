import nuke
import hiero
import os
import sys
import time

# import baittasks module
pathToBaitTasksPythonFolder = os.environ.get("BAIT_TASKS_PYTHON_DIR", None)
assert pathToBaitTasksPythonFolder != None
if pathToBaitTasksPythonFolder not in sys.path:
    sys.path.append(pathToBaitTasksPythonFolder)
import BaitTasks

# method to generate bait tasks to create web reviewable version of copied sequence frames
def createWebReviewable(exporter, versionInfo):
    # create output nukescript path
    cleanedPathToFrames = versionInfo["sg_path_to_frames"].replace(os.path.sep, "/")
    pathToFramesNoExt = cleanedPathToFrames.split(".####")[0]
    outputNukeScriptPath = "{}.nk".format(pathToFramesNoExt)

    # get path to the bait tasks transcode templates
    pathToBaitTasksFolder = os.environ.get("BAIT_TASKS_DIR", None)
    if not pathToBaitTasksFolder:
        exporter.app.log_error("Could not find Bait Tasks directory in os.environ")
        return False

    # get frame in/out from version
    frameIn = versionInfo["sg_first_frame"]
    frameOut = versionInfo["sg_last_frame"]

    # set the deadline vars
    submitTime = time.strftime("%H:%M", time.localtime())
    batchGroupName = batchGroupName = "{} | Ingest | {} | {}".format(versionInfo["code"], versionInfo["project"]["name"], submitTime)
    nukeVersion = "{}.{}".format(nuke.nuke.NUKE_VERSION_MAJOR, nuke.nuke.NUKE_VERSION_MINOR)
    nukeMachineList = []
    ingestPool = 'ingest'
    ingestScondaryPool = None

    # collate tasks
    tasks = []

    # create task to generate web-reviewable nuke script from transcode templates
    outputMovPath = outputNukeScriptPath.replace(".nk", ".mov") #TODO - pull from template

    # filter for ACES colour management transcode
    templateScriptPath = os.path.join(pathToBaitTasksFolder, "nukescripts", "TranscodeScriptExample.nk")
    if 'aces' in hiero.core.projects()[0].extractSettings()['ocioConfigName']:
        templateScriptPath = os.path.join(pathToBaitTasksFolder, "nukescripts", "TranscodeScriptACES.nk")

    nukeWebReviewableScriptCreationTask = BaitTasks.Tasks.Nuke.NukeGenerateScriptFromTranscodeTemplate(
        cleanedPathToFrames,
        outputMovPath,
        templateScriptPath,
        outputNukeScriptPath,
        frameIn,
        frameOut,
        supressFileSavedCheck=True,
        supressWriteNodeCheck=True
    )
    tasks.append(nukeWebReviewableScriptCreationTask)

    #Submit web-reviewable script to deadline
    submitWebReviewableToDeadlineTask = BaitTasks.Tasks.Deadline.SubmitNukeScript(
        "WebReviewable: {}".format(os.path.basename(outputNukeScriptPath.replace(".nk", ""))),
        outputNukeScriptPath,
        outputMovPath,
        frameIn,
        frameOut,
        comment="The web-reviewable render",
        nukeVersion=nukeVersion,
        pool=ingestPool,
        secondaryPool=ingestScondaryPool,
        machineList=nukeMachineList,
        batchGroupName=batchGroupName,
        sameWorker=True
    )
    tasks.append(submitWebReviewableToDeadlineTask)

    #Add an upload web reviewable shotgrid subtask. This will run via a RunBaitTasks task that we'll create in a second
    uploadWebReviewableVersionMediaTask = BaitTasks.Tasks.ShotGrid.SubTasks.ShotGridUploadWebReviewable(
        outputMovPath,
        versionInfo["project"]["id"],
        entityType="Version",
        entityID=versionInfo["id"],
    )

    #Run the webreviewable upload once the render is complete
    runWebReviewableUploadAndStatusUpdateShotgunTasks = BaitTasks.Tasks.Deadline.RunBaitTasks(
        "Upload Web-Reviewable",
        [BaitTasks.Tasks.ShotGrid.ShotGridUpdater([uploadWebReviewableVersionMediaTask])], 
        "2.7",
        "Uploading of web-reviewable media",
        machineList=nukeMachineList,
        batchGroupName=batchGroupName,
        upstreamDeadlineTaskIDs=[submitWebReviewableToDeadlineTask.id]
    )
    tasks.append(runWebReviewableUploadAndStatusUpdateShotgunTasks)

    exporter.app.log_info("Created {} BaitTasks".format(len(tasks)))
    for task in tasks:
        exporter.app.log_info(task.serialise())
        exporter.app.log_info("")

    #Run the Tasks
    BaitTasks.Handler.default.addTasksToQueue(tasks, autoStart=True)
    exporter.app.log_info("Ran {} BaitTasks".format(len(tasks)))