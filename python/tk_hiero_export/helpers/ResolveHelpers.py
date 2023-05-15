def getResolvedPathForTrackItem(shotTaskInstance, trackItem):
    # todo - determine resolved export path for the passed in item
    # we can use Hiero's resolvers to do this.
    # there's likely a way we can easily spawn a task here to use with FnResolveTable.resolve
    # but I don't have time to figure that out right now.
    # instead I'll duplicate the current resolve table, and override the values
    # that actually change between the items we'll pass into this function.
    # right now, that's just {track}
    resolver = shotTaskInstance._resolver
    resolverDuplicate = resolver.duplicate()
    resolverDuplicate.addResolver("{track}", "replaces track token with track name, filling spaces with underscores", trackItem.parentTrack().name().replace(" ", "_"))
    thisItemResolvedExportPath = resolverDuplicate.resolve(shotTaskInstance, shotTaskInstance._exportPath, isPath=True)
    
    # at this point the path is likely a mix of forward/backslashes due to how nuke/SG handle things differently.
    # make them all forward slashes (i.e. nuke style)
    return thisItemResolvedExportPath.replace("\\", "/")