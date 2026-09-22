# Guarding the output directory

The site generator empties its output directory at the start of every run. It
does so because the previous run's files are not tracked anywhere: a profile
that was unpublished since the last generation would otherwise remain on disk
as an orphaned page, and no record exists from which to determine which files
to remove individually.

The directory path comes from the `PUBLIC_SITE_DIR` setting or from the
`--output-dir` argument of the command-line generator. Both are free-form
paths, and neither is validated against anything. A value such as `/var/www` or
a home directory is accepted as readily as the intended one, and the deletion
that follows is recursive.

The generator therefore requires a marker file named `.flexmapping-site` in the
directory before it removes anything. Three cases arise. A directory that does
not exist is created and receives the marker. An empty directory receives the
marker. A non-empty directory without the marker causes the run to stop with an
error naming the path.

The marker is written before any content, so that a run interrupted midway still
leaves a directory that the next run is permitted to clear.

This protects against a mistyped or misconfigured path. It does not protect
against a path that is deliberately prepared: an operator who creates the marker
in a directory used for something else has removed the guard. The intended use
is a directory reserved for the generated site, and the documentation states
that in the installation and system impact chapters.
