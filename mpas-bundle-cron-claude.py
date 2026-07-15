#!/usr/bin/env python3
"""Build mpas-bundle and run mpas-jedi ctests.

mpas-bundle may be built with the gnu, intel, and/or nvhpc tool chains.
After running mpas-jedi ctests the results are assembled into an html
document, which is copied to the web pages directory on an mmm server.

This script assumes the mpas-bundle repository has been cloned into

    <some_dir>/<mpas-bundle_dir>   # directory mpas-bundle has been cloned to

It will create the following directory layout if it doesn't already exist,
adjacent to the bundle source directory:

    <some_dir>/build-gnu-2p     # gnu tool chain, double precision
    <some_dir>/build-gnu-1p     # gnu tool chain, single precision
    <some_dir>/build-intel-2p   # intel tool chain, double precision
    <some_dir>/build-intel-1p   # intel tool chain, single precision

This script is expected to be run via cron, but can be run manually as
well; run with --help for usage.

Direct Python translation of mpas-bundle-cron.sh, using only the Python
standard library.
"""

import argparse
import atexit
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------
# Constants / module-level state (mirrors the bash script's globals)
# --------------------------------------------------------------------------

LOCK_FILE_NAME = "mpas_bundle_cron.lock"

# available PBS queues
MAIN_Q = "main@desched1"       # normal cpu hours are charged
PREEMPT_Q = "preempt@desched1"  # charged @ .3 * regular rate, job may not run to completion
DEV_Q = "develop@desched1"      # shared nodes, charged only for the no. of cpus used

# where to copy html output files on the mmm web pages server
DEFAULT_HTML_DIR = "/web/htdocs/projects/mpas-jedi/weekly-ctests"

CTEST_LOGFILE = "ctest.pbs.sh.log"
CTEST_IODA_LOGFILE = "ctest-ioda.pbs.sh.log"

REMOTE_HOST = "derecho.hpc.ucar.edu"
WEB_HOST = "eris.mmm.ucar.edu"

TIMESTAMP = datetime.now().strftime("%Y-%m-%d-%H-%M")

# set by init_logs(); read by log() and make_html()
LOGFILE = None
HTML_BODY_FILE = None

# set by acquire_lock(); read by remove_lock()
LOCK_FILE = None


# --------------------------------------------------------------------------
# Logging / locking
# --------------------------------------------------------------------------

def init_logs(cron_logdir):
    """Create the cron log directory and initialize LOGFILE/HTML_BODY_FILE.

    cron_logdir is created if missing. LOGFILE is a per-run log file
    stamped with TIMESTAMP; HTML_BODY_FILE accumulates the html table rows
    from previous runs so make_html() can prepend new rows to it.
    """
    global LOGFILE, HTML_BODY_FILE
    os.makedirs(cron_logdir, exist_ok=True)
    LOGFILE = os.path.join(cron_logdir, f"mpas-bundle-cron.log.{TIMESTAMP}")
    Path(LOGFILE).touch()
    HTML_BODY_FILE = os.path.join(cron_logdir, "body.html")


def log(message):
    """Print message to stdout and, once LOGFILE exists, append it there too.

    Equivalent to the bash log() function's `echo -e "$1" | tee -a $LOGFILE`.
    """
    print(message)
    if LOGFILE and os.path.isfile(LOGFILE):
        with open(LOGFILE, "a") as f:
            f.write(message + "\n")


def remove_lock():
    """Remove the run lock file, if any. Registered as an atexit handler."""
    if LOCK_FILE and os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)


def acquire_lock(lock_file, retries=360, wait_secs=10, stale_secs=72000):
    """Acquire an exclusive run lock, mirroring `lockfile -10 -r 360 -l 72000`.

    Retries every wait_secs seconds, up to retries times (360 * 10s = 1hr),
    treating any existing lock file older than stale_secs (20hrs) as stale
    and removing it before trying again. Returns True once the lock file has
    been created, False if all retries were exhausted.
    """
    global LOCK_FILE
    LOCK_FILE = lock_file
    for attempt in range(retries + 1):
        if os.path.exists(lock_file):
            age = time.time() - os.path.getmtime(lock_file)
            if age > stale_secs:
                log(f"removing stale lock file {lock_file} (age {age:.0f}s)")
                os.remove(lock_file)
        try:
            fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            if attempt < retries:
                time.sleep(wait_secs)
    return False


def another_instance(lock_file):
    """Report that lock_file is already held by another run, then exit(1)."""
    log(f"Cannot acquire lock on {lock_file}")
    log("There is another instance running, exiting")
    sys.exit(1)


# --------------------------------------------------------------------------
# Subprocess helpers
# --------------------------------------------------------------------------

def run(cmd, env=None, cwd=None):
    """Run cmd (a list of args, no shell), logging the command and its output.

    Combines stdout/stderr like bash's `|&`. Does not raise on non-zero
    exit; callers check result.returncode themselves, matching the original
    script's style of explicit error checks rather than `set -e`.
    """
    log(" ".join(str(c) for c in cmd))
    result = subprocess.run(
        cmd, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    if result.stdout:
        log(result.stdout.rstrip("\n"))
    return result


def run_and_tee_local(cmd, tee_file):
    """Run cmd, streaming combined output to stdout, LOGFILE, and tee_file.

    Equivalent to bash's `cmd |& tee tee_file` where tee runs locally (used
    for run_cmake(), which ssh's to derecho but tees the output on the
    machine running this script).
    """
    log(" ".join(str(c) for c in cmd))
    with open(tee_file, "w") as tf:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        for line in proc.stdout:
            sys.stdout.write(line)
            tf.write(line)
            if LOGFILE:
                with open(LOGFILE, "a") as lf:
                    lf.write(line)
        proc.wait()
    return proc.returncode


# --------------------------------------------------------------------------
# PBS helpers
# --------------------------------------------------------------------------

def check_pbs_return(jobno):
    """Return the PBS Exit_status for jobno, or 1 if it can't be determined.

    Runs `qstat -x -f jobno` (bypassing any qstat cache) and looks for the
    Exit_status line, matching bash's check_pbs_return().
    """
    env = dict(os.environ, QSCACHE_BYPASS="1")
    result = run(["qstat", "-x", "-f", jobno], env=env)
    status_line = None
    for line in result.stdout.splitlines():
        if "Exit_status" in line:
            status_line = line
            break
    log(f"jobno={jobno} pbs_status={status_line}")
    if status_line:
        try:
            return int(status_line.split()[2])
        except (IndexError, ValueError):
            return 1
    return 1


def queue_wait(job, pcode, secs):
    """Poll `qstat job` every secs seconds until it enters/leaves the queue.

    If pcode > 0, waits until the job appears in the queue. If pcode == 0,
    waits until the job leaves the queue. Mirrors bash queue_wait().
    """
    def in_queue():
        result = subprocess.run(
            ["qstat", job], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return result.returncode == 0

    present = in_queue()
    log(f"queue_wait started job={job} pcode={pcode} rc={0 if present else 1}")
    if pcode > 0:
        while not present:
            time.sleep(secs)
            present = in_queue()
    else:
        while present:
            time.sleep(secs)
            present = in_queue()
    log(f"queue_wait finished job={job} pcode={pcode} rc={0 if present else 1}")


def get_walltime(jobno):
    """Return the `used.walltime` field for jobno from `qstat -xf`, or '' if absent."""
    result = run(["qstat", "-xf", jobno])
    for line in result.stdout.splitlines():
        if "used.walltime" in line:
            parts = line.split()
            if len(parts) >= 3:
                return parts[2]
    return ""


# --------------------------------------------------------------------------
# HTML page helpers
# --------------------------------------------------------------------------

def print_header(outfile):
    """Append the HTML page header (style block + results table header row) to outfile."""
    header_lines = [
        "<!DOCTYPE html> <html> <head> <style>",
        "table { font-family: arial, sans-serif; border-collapse: collapse; width: 100%; }",
        "td, th { border: 1px solid #dddddd; text-align: left; padding: 8px; }",
        "th { top:0; position:sticky; background-color:white; border: 1px solid black; }",
        "tr:nth-child(even) { background-color: #dddddd; } </style> </head>",
        "<body> <h2>mpas-bundle mpas-jedi ctest results</h2>",
        "<table> <tr> <th>Date</th> <th>Results</th> <th>Spack</th> "
        "<th>CC </th> <th>Tools</th> <th>Stats</th></tr>",
    ]
    with open(outfile, "a") as f:
        for line in header_lines:
            f.write(line + "\n")


def print_footer(outfile):
    """Append the HTML page footer (prior-year index links + closing tags) to outfile."""
    with open(outfile, "a") as f:
        f.write("</table><table> <tr> <th><h2>Year</h2></th>\n")
        f.write('<tr><td> 2025 </td> <td><a href=2025/index.html>2025 test results</a> </td> </tr>\n')
        f.write('<tr><td> 2024 </td> <td><a href=2024/index.html>2024 test results</a> </td> </tr>\n')
        f.write("<tr><td> </td> </tr>\n")
        f.write("</table> </body> </html>\n")


# --------------------------------------------------------------------------
# Remote build steps
# --------------------------------------------------------------------------

def run_cmake(build_dir, bundle_dir, cc, dbl_p, build_type, log_dir):
    """Generate a cmake driver script and execute it on the remote host.

    Writes a shell script (on the shared filesystem under log_dir) that
    sources the compiler-specific mpas-bundle environment, runs
    `make update` if a Makefile is already present, then invokes cmake with
    the options used for the ctest build. The script is executed via ssh so
    it runs on the derecho login node (needed for reliable internet access),
    and its output is teed locally to <script>.log. Mirrors bash run_cmake().
    """
    cmake_script = os.path.join(log_dir, "run_cmake.sh")
    script_body = (
        "#!/bin/bash\n"
        "#\n"
        f"cd {build_dir} && source {bundle_dir}/env-setup/{cc}-derecho.sh && "
        f"source {bundle_dir}/env-setup/ioda-modules.list && "
        'if [ -f Makefile ]; then echo "make update" && make update |& tee make.update.log; fi && '
        "cmake -DCMAKE_VERBOSE_MAKEFILE=ON -DBUNDLE_SKIP_RTTOV=ON "
        f"-DMPAS_DOUBLE_PRECISION={dbl_p} -DBUILD_IODA_CONVERTERS=ON "
        f"-DCMAKE_BUILD_TYPE={build_type} ctest_update {bundle_dir};\n"
    )
    with open(cmake_script, "w") as f:
        f.write(script_body)
    os.chmod(cmake_script, 0o755)

    log_file = f"{cmake_script}.log"
    log(f"ssh {REMOTE_HOST} {cmake_script} |& tee {log_file}")
    run_and_tee_local(["ssh", REMOTE_HOST, cmake_script], log_file)


def check_git_changes(work_dir, check_changes_log, log_dir):
    """Check every git submodule under work_dir for upstream changes.

    Writes a helper script (on the shared filesystem) that, when run on the
    remote host, walks each first-level subdirectory of work_dir, and for
    any that are git repositories, fetches and compares local HEAD to the
    tracked branch's remote HEAD. Differences are pulled in and noted in
    check_changes_log (run remotely, so it must resolve there too), and a
    marker file is touched. Returns 1 if any repo was updated, 0 otherwise.
    Mirrors bash check_git_changes().
    """
    check_script = os.path.join(log_dir, "check_changes.sh")
    update_file = os.path.join(log_dir, "files_changed.lock")
    if os.path.exists(update_file):
        os.remove(update_file)

    script_body = """#!/bin/bash -l
#
# check to see if any source files changed in git.
# this is meant to be called from automated scripts.

# touch %(update_file)s if sources changed
check_for_changes() {
  # traverse subdirectories
  dirs=$(ls -d */)
  for subdir in $dirs;
  do

    # skip directories which don't have a git repo
    if [ ! -d "${subdir}/.git" ]; then
      continue
    fi

    echo $subdir
    cd "$subdir"

    # get latest code and see if it has changed
    git fetch >& /dev/null
    local branch=$(git rev-parse --abbrev-ref HEAD)
    local remote=$(git remote get-url origin)
    local local_commit=$(git rev-parse --short HEAD)
    local remote_commit=$(git rev-parse --short origin/${branch})
    if [ "$local_commit" != "$remote_commit" ]; then
      echo "updating ${remote} in branch ${branch} to sha $remote_commit." &>> %(check_changes_log)s
      git pull &>> %(check_changes_log)s
      echo "${remote} in branch ${branch} has been updated to sha $remote_commit."
      touch %(update_file)s
    else
      echo "No updates found for ${remote} in branch ${branch}, sha $local_commit."
    fi

    cd ..
  done
}

echo "work_dir %(work_dir)s"
echo "sync_file %(update_file)s"
cd %(work_dir)s
check_for_changes
""" % {
        "update_file": update_file,
        "check_changes_log": check_changes_log,
        "work_dir": work_dir,
    }

    with open(check_script, "w") as f:
        f.write(script_body)
    os.chmod(check_script, 0o755)

    remote_cmd = f"{check_script} |& tee {check_changes_log}"
    log(f"ssh {REMOTE_HOST} {remote_cmd}")
    run(["ssh", REMOTE_HOST, remote_cmd])

    ret_code = 0
    if os.path.exists(update_file):
        log(f"update file {update_file} exists")
        ret_code = 1
        os.remove(update_file)
    return ret_code


# --------------------------------------------------------------------------
# ctest result handling
# --------------------------------------------------------------------------

def get_ctest_summary(logfile, make_job, ctest_job, test_name):
    """Summarize a ctest run from its log file.

    If logfile doesn't exist, the make (or ctest) job was likely aborted;
    the summary explains which job failed. Otherwise, extracts the ctest
    "NN% tests passed" style summary line. Returns (summary, retval) where
    retval is 0 on success, matching bash get_ctest_summary().
    """
    if not os.path.isfile(logfile):
        make_rc = check_pbs_return(make_job)
        if make_rc != 0:
            summary = f"make job failed return code {make_rc}"
        else:
            ctest_rc = check_pbs_return(ctest_job)
            if ctest_rc != 0:
                summary = f"{test_name} failed {ctest_rc}"
            else:
                summary = f"{test_name} didn't run"
        return summary, 1

    summary = f"{test_name} "
    with open(logfile) as f:
        for line in f:
            if re.search(r"tests .*passed", line):
                fields = line.split()
                if len(fields) >= 3:
                    summary += f"{fields[0]} {fields[2]}"
                break
    return summary, 0


def run_ctests(scripts, cc, make_job, timestamp, build_type, account, queue):
    """Submit and wait for the mpas and ioda PBS ctest jobs for one build.

    Generates ctest.pbs.sh / ctest-ioda.pbs.sh via run_make.bundle.sh,
    submits both dependent on make_job succeeding, waits for the mpas ctest
    job to enter then leave the queue, and gathers pass/fail summaries and
    walltimes for both suites. Returns (html_results, mpas_ctest_time,
    ioda_ctest_time). Mirrors bash run_ctests().
    """
    mpas_href = f'href="./results/ctest.results.log.{timestamp}"'
    ioda_href = f'href="./results/ctest-ioda.results.log.{timestamp}"'

    for logfile in (CTEST_LOGFILE, CTEST_IODA_LOGFILE):
        if os.path.exists(logfile):
            shutil.move(logfile, logfile + ".old")

    run([f"{scripts}/run_make.bundle.sh", "-A", account, "-q", queue, "-p", "economy",
         "-x", "ctest", "-c", cc, "-N", f"cron-{cc}-ctest-{build_type}", "-m", "-n"])
    result = run(["qsub", "-W", f"depend=afterok:{make_job}", "./ctest.pbs.sh"])
    if result.returncode != 0:
        log("cannot connect to Derecho PBS")
        sys.exit(1)
    ctest_job = result.stdout.strip()

    run([f"{scripts}/run_make.bundle.sh", "-A", account, "-q", queue, "-p", "economy",
         "-x", "ctest-ioda", "-c", cc, "-N", f"cron-{cc}-ctest-{build_type}", "-m", "-n"])
    result = run(["qsub", "-W", f"depend=afterok:{make_job}", "./ctest-ioda.pbs.sh"])
    if result.returncode != 0:
        log("cannot connect to Derecho PBS")
        sys.exit(1)
    ctest_ioda_job = result.stdout.strip()

    # wait for the ctest job to show up in the queue, check every 5 seconds
    queue_wait(ctest_job, 1, 5)
    # wait for the ctest job to finish, check every 60 seconds
    # assume the mpas-ctest job will take longer than the ioda ctest job.
    queue_wait(ctest_job, 0, 60)

    mpas_ctest_time = get_walltime(ctest_job)
    ioda_ctest_time = get_walltime(ctest_ioda_job)

    mpas_summary, retcode = get_ctest_summary(CTEST_LOGFILE, make_job, ctest_job, "mpas-ctest")
    log(f"run_ctests() summary:{mpas_summary} href:{mpas_href} ctest_time:{mpas_ctest_time} return:{retcode}")
    if retcode != 0:
        mpas_href = ""
        mpas_ctest_time = "NA"

    ioda_summary, retcode = get_ctest_summary(CTEST_IODA_LOGFILE, make_job, ctest_ioda_job, "ioda-ctest")
    log(f"run_ctests() iodasummary:{ioda_summary} iodahref:{ioda_href} iodactest_time:{ioda_ctest_time} return:{retcode}")
    if retcode != 0:
        ioda_href = ""
        ioda_ctest_time = "NA"

    html_results = f'<td><a {mpas_href}>{mpas_summary}</a> -- <a {ioda_href}>{ioda_summary}</a> </td>'
    return html_results, mpas_ctest_time, ioda_ctest_time


# --------------------------------------------------------------------------
# make_html() and its small text-processing helpers
# --------------------------------------------------------------------------

def _grep_first(pattern, path):
    """Return the first line in path matching regex pattern, or '' if none/missing."""
    try:
        with open(path) as f:
            for line in f:
                if re.search(pattern, line):
                    return line
    except FileNotFoundError:
        pass
    return ""


def _field(text, sep, index):
    """Return the 1-based index'th field of text split on sep (whitespace if sep is None)."""
    if not text:
        return ""
    parts = text.split(sep) if sep else text.split()
    i = index - 1
    return parts[i].strip() if 0 <= i < len(parts) else ""


def _egrep_context(path, pattern, after):
    """Return lines from path matching pattern plus `after` following lines.

    Equivalent to `egrep -A after 'pattern' path`, without duplicating lines
    where matches are close enough that their contexts overlap.
    """
    with open(path) as f:
        lines = f.readlines()
    regex = re.compile(pattern)
    selected = set()
    for i, line in enumerate(lines):
        if regex.search(line):
            for j in range(i, min(len(lines), i + after + 1)):
                selected.add(j)
    return [lines[i] for i in sorted(selected)]


def make_html(dest_dir, make_job, cc, timestamp, mpas_ctest_time, ioda_ctest_time,
              summary, sha_file, build_type, bundle_dir, queue):
    """Build the results HTML page for one build and publish it to the web server.

    Extracts the spack-stack/compiler/mpich versions from the toolchain's
    env-setup script, computes the PBS make walltime, prepends a new
    results row to the running history kept in HTML_BODY_FILE, rewrites
    index.html with header + accumulated rows + footer, then scp's the
    ctest log excerpts, the git-sha file, and the new index page to
    WEB_HOST, atomically repointing the index.html symlink there. Mirrors
    bash make_html().
    """
    log(f"make_html() dest_dir: {dest_dir} make_job={make_job} mpas_ctest_time={mpas_ctest_time}")
    log(f"            ioda_ctest_time={ioda_ctest_time} cc={cc} timestamp={timestamp} summary={summary}")
    log(f"            sha_file={sha_file} sha_file:t={os.path.basename(sha_file)}")

    bld = "Release"
    if build_type == "Debug":
        bld = build_type
    elif build_type == "RelWithDebInfo":
        bld = "Rel-Deb"

    env_file = os.path.join(bundle_dir, "env-setup", f"{cc}-derecho.sh")

    spack_line = _grep_first("spack-stack-", env_file)
    spack_stack = ""
    slash_fields = spack_line.split("/")
    if len(slash_fields) >= 8:
        spack_stack = _field(slash_fields[7], "-", 3)
    log(f"spack-stack: {spack_stack}")

    comp = {"gnu": "gcc", "intel": "intel", "nvhpc": "nvhpc"}.get(cc, "")
    compiler_line = _grep_first(rf"load .*{comp}", env_file)
    compiler = _field(_field(compiler_line, None, 3), "-", 2)
    log(f"compiler: {compiler}")

    mpich_line = _grep_first(r"load .*cray-mpich", env_file)
    mpich = _field(_field(mpich_line, None, 3), "-", 3)
    log(f"mpich: {mpich}")

    make_time = get_walltime(make_job)

    queue_short = queue.removesuffix("@desched1")
    stats = (f"<a href=./shas/{os.path.basename(sha_file)}> Q:{queue_short} make:{make_time} "
             f"mpas_ctest:{mpas_ctest_time} ioda_ctest:{ioda_ctest_time} </a>")

    row = (f"<tr><td>{timestamp}</td> {summary} <td>{spack_stack}</td> <td>{cc}</td> "
           f"<td>{bld} {compiler} {mpich}</td> <td>{stats}</td> ")

    with open("body.html", "w") as f:
        f.write(row + "\n")
        if os.path.isfile(HTML_BODY_FILE):
            with open(HTML_BODY_FILE) as old:
                f.write(old.read())
    shutil.copy("body.html", HTML_BODY_FILE)

    if os.path.exists("index.html"):
        os.remove("index.html")
    print_header("index.html")
    with open("index.html", "a") as idx, open("body.html") as body:
        idx.write(body.read())
    print_footer("index.html")
    os.remove("body.html")

    dest = f"{WEB_HOST}:{dest_dir}"

    if os.path.isfile(CTEST_LOGFILE):
        resultsfile = f"ctest.results.log.{timestamp}"
        with open(resultsfile, "w") as rf:
            rf.write(f"{timestamp}\n\n")
            rf.writelines(_egrep_context(CTEST_LOGFILE, r"Test|Start", 20))
        log(f"scp ./{resultsfile} {dest}/results/")
        if run(["scp", resultsfile, f"{dest}/results/"]).returncode != 0:
            log("scp ctest_results failed")
        shutil.move(resultsfile, "ctest.results.log.old")
    else:
        log(f"{CTEST_LOGFILE} doesn't exist")

    if os.path.isfile(CTEST_IODA_LOGFILE):
        iodaresultsfile = f"ctest-ioda.results.log.{timestamp}"
        with open(iodaresultsfile, "w") as rf:
            rf.write(f"{timestamp}\n\n")
            rf.writelines(_egrep_context(CTEST_IODA_LOGFILE, r"Test|Start", 20))
        log(f"scp ./{iodaresultsfile} {dest}/results/")
        if run(["scp", iodaresultsfile, f"{dest}/results/"]).returncode != 0:
            log("scp ctest_results failed")
        shutil.move(iodaresultsfile, "ctest-ioda.results.log.old")
    else:
        log(f"{CTEST_IODA_LOGFILE} doesn't exist")

    log(f"scp {sha_file} {dest}/shas")
    if run(["scp", sha_file, f"{dest}/shas"]).returncode != 0:
        log(f"scp {sha_file} failed")

    # clean up old index files by putting them in a tar file
    log(f"ssh {WEB_HOST} cd {dest_dir} && tar --remove-files -rf index.tar index.2*")
    run(["ssh", WEB_HOST, f"cd {dest_dir} && tar --remove-files -rf index.tar index.2*"])

    indexed_name = f"index.{timestamp}.html"
    shutil.move("index.html", indexed_name)
    log(f"scp ./{indexed_name} {dest}")
    if run(["scp", indexed_name, dest]).returncode != 0:
        log("scp index failed")
    os.remove(indexed_name)

    log(f"ssh {WEB_HOST} cd {dest_dir} && rm -f index.html && ln -s {indexed_name} index.html")
    run(["ssh", WEB_HOST, f"cd {dest_dir} && rm -f index.html && ln -s {indexed_name} index.html"])


# --------------------------------------------------------------------------
# Top-level build orchestration
# --------------------------------------------------------------------------

def build_and_test(cc, dbl_p, html_dir, do_run_cmake, sha_file, build_type, suffix, args, timestamp):
    """Run cmake (optionally), make, and ctest for one toolchain, then publish results.

    Picks a build directory based on compiler/precision/build-type/suffix,
    optionally regenerates the cmake cache, submits a PBS make job via
    run_make.bundle.sh, and then either runs the double-precision ctest
    suite or (for single precision) waits for make and refreshes a
    `_latest` symlink on success. Finishes by calling make_html() to
    publish the results row. Mirrors bash build_and_test().
    """
    build_dir_suffix = "2p" if dbl_p == "ON" else "1p"
    scripts = os.path.join(args.bundle_dir, "env-setup")

    build_dir = os.path.join(args.build_dir_root, f"build-{cc}-{build_dir_suffix}")
    if suffix:
        build_dir += f"_{suffix}"
    nthreads = []
    if build_type != "Release":
        build_dir += f"_{build_type}"
        nthreads = ["-t", "56"]

    os.makedirs(build_dir, exist_ok=True)
    log(f"BUNDLE_DIR {args.bundle_dir}")
    log(f"BUILD_DIR {build_dir}")
    try:
        os.chdir(build_dir)
    except OSError:
        log(f"cannot cd {build_dir}")
        sys.exit(1)
    log(f"building in: {os.getcwd()}")

    # run cmake on a login node (compute nodes have poor internet transmission)
    # block until cmake finishes
    if do_run_cmake:
        log(f"run_cmake {build_dir} {args.bundle_dir} {cc} {dbl_p} {build_type}")
        run_cmake(build_dir, args.bundle_dir, cc, dbl_p, build_type, args.log_dir)

    if os.path.exists("make.pbs.sh.log"):
        shutil.move("make.pbs.sh.log", "make.pbs.sh.log.old")

    run([f"{scripts}/run_make.bundle.sh", "-A", args.account, "-q", args.queue, "-p", "economy",
         "-x", "make", "-c", cc, "-N", f"cron-{cc}-make-{build_type}", *nthreads, "-m", "-n"])
    result = run(["qsub", "make.pbs.sh"])
    if result.returncode != 0:
        log("cannot connect to Derecho PBS")
        sys.exit(1)
    make_job = result.stdout.strip()
    log(f"{cc} make: {make_job}")

    mpas_ctest_time = "NA"
    ioda_ctest_time = "NA"

    # only run ctest for double precision builds
    if dbl_p == "ON":
        summary, mpas_ctest_time, ioda_ctest_time = run_ctests(
            scripts, cc, make_job, timestamp, build_type, args.account, args.queue
        )
        log(f"build_and_test() summary:{summary} mpas_ctest_time:{mpas_ctest_time} "
            f"ioda_ctest_time:{ioda_ctest_time}")
    else:
        # wait for the make job to show up in the queue, check every 5 seconds
        queue_wait(make_job, 1, 5)
        # wait for the make job to finish, check every 60 seconds
        queue_wait(make_job, 0, 60)
        summary = "Single precision build - no ctests run"

        # make a symlink to the latest single precision build on success
        make_rc = check_pbs_return(make_job)
        if make_rc == 0:
            build_dir_root = build_dir.split("_")[0]
            latest_dir = f"{build_dir_root}_latest"
            log(f"rm {latest_dir}")
            if os.path.islink(latest_dir) or os.path.exists(latest_dir):
                os.remove(latest_dir)
            log(f"ln -s {os.getcwd()} {latest_dir}")
            os.symlink(os.getcwd(), latest_dir)
        else:
            summary = f"single precision make job failed return code {make_rc}"

    log(f"calling make_html() dir: {html_dir} make_job {make_job} mpas_ctest_time {mpas_ctest_time} "
        f"ioda_ctest_time {ioda_ctest_time} cc {cc} timestamp {timestamp} summary {summary}")
    make_html(html_dir, make_job, cc, timestamp, mpas_ctest_time, ioda_ctest_time,
              summary, sha_file, build_type, args.bundle_dir, args.queue)


# --------------------------------------------------------------------------
# CLI / entry point
# --------------------------------------------------------------------------

def parse_args(argv=None):
    """Parse command-line arguments, mirroring the bash script's getopts flags."""
    parser = argparse.ArgumentParser(
        description="Build mpas-bundle and run mpas-jedi ctests, publishing results as HTML."
    )
    parser.add_argument("-d", dest="bundle_dir", required=True,
                         help="directory where the mpas-bundle repo has been cloned to")
    parser.add_argument("-b", dest="build_dir_root", default="",
                         help="root directory to create build-<compiler>-<precision> dirs in "
                              "(default: <bundle_dir>/..)")
    parser.add_argument("-c", dest="tools", required=True,
                         help="one of gnu, intel, nvhpc, or all")
    parser.add_argument("-x", dest="suffix", default="",
                         help="suffix to add to the build directory")
    parser.add_argument("-q", dest="queue", default=MAIN_Q,
                         help=f"{MAIN_Q}, {DEV_Q} or {PREEMPT_Q}, defaults to {MAIN_Q}")
    parser.add_argument("-a", dest="account", default="nmmm0015",
                         help="account to use when submitting PBS jobs")
    parser.add_argument("-p", dest="precision", default="2", choices=["1", "2"],
                         help="1 or 2, defaults to 2 (double)")
    parser.add_argument("-t", dest="build_type", default="Release",
                         help="cmake build type: Release, Debug, or RelWithDebInfo")
    parser.add_argument("-l", dest="lock_file", default="",
                         help=f"absolute path to the lock file, default is <bundle_dir>/{LOCK_FILE_NAME}")
    parser.add_argument("-o", dest="html_dir", default=DEFAULT_HTML_DIR,
                         help="directory the html files will be copied to")
    parser.add_argument("-f", dest="force_build", action="store_true",
                         help="force-build, always build even if no source changed since last build")
    parser.add_argument("-n", dest="skip_cmake", action="store_true",
                         help="don't run cmake")
    parser.add_argument("--log-dir", dest="log_dir",
                         default=os.path.join(str(Path.home()), "my_cron_logs"),
                         help="directory to write cron logs to")
    return parser.parse_args(argv)


def main():
    """Entry point: parse args, validate, acquire the run lock, check for
    upstream source changes, and dispatch build_and_test() for each
    requested toolchain. Mirrors the bottom (non-function) part of the
    bash script.
    """
    args = parse_args()
    init_logs(args.log_dir)
    log(f"commandline: {' '.join(sys.argv)}")

    if not os.path.isdir(args.bundle_dir):
        log(f"source dir {args.bundle_dir} does not exist")
        sys.exit(1)

    if not args.build_dir_root:
        args.build_dir_root = os.path.join(args.bundle_dir, "..")
    elif not os.path.isdir(args.build_dir_root):
        log(f"output dir {args.build_dir_root} does not exist")
        sys.exit(1)

    if args.queue not in (MAIN_Q, PREEMPT_Q, DEV_Q):
        log(f'queue "{args.queue}" is invalid')
        sys.exit(1)

    dbl_precision = "ON" if args.precision == "2" else "OFF"
    log(f"q:{args.queue} precision: {args.precision} {dbl_precision} force: {int(args.force_build)}")

    # acquire an exclusive lock on our lock file to make sure only one copy
    # of this script is running at a time. wait 10 seconds between attempts,
    # retry 360 times (1hr), delete a lockfile which is over 20 hours old.
    lock_file = args.lock_file or os.path.join(args.bundle_dir, LOCK_FILE_NAME)
    if not acquire_lock(lock_file):
        another_instance(lock_file)
    atexit.register(remove_lock)
    log(f"lockfile: {lock_file}")

    scriptdir = os.path.dirname(os.path.abspath(__file__))
    log(f"[{TIMESTAMP}]: Running {sys.argv[0]} on {socket.gethostname()}\n"
        f"\tfrom {os.getcwd()}\n\tscriptdir={scriptdir}")
    log(f"using job queue {args.queue}")

    # check for any changed source, store all current git sha's in a file
    sha_file = os.path.join(args.log_dir, f"git_shas.{TIMESTAMP}")
    git_changes = check_git_changes(args.bundle_dir, sha_file, args.log_dir)
    log(f"check_git_changes returned {git_changes}")

    # check to see if any source files changed, do nothing if no changes
    force_build = args.force_build
    if not force_build and git_changes == 1:
        force_build = True
        log("forcing build, check_git_changes returned 1")

    if not force_build:
        log("no source changes, not running")
        return

    log(f"building with tools {args.tools}")
    do_run_cmake = not args.skip_cmake
    for cc in ("gnu", "intel", "nvhpc"):
        if args.tools in (cc, "all"):
            build_and_test(cc, dbl_precision, args.html_dir, do_run_cmake, sha_file,
                            args.build_type, args.suffix, args, TIMESTAMP)


if __name__ == "__main__":
    main()
