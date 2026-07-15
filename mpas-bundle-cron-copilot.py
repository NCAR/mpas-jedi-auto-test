#!/usr/bin/env python3
"""
mpas-bundle-cron.py

Converted from mpas-bundle-cron.sh to Python using only standard library modules.

This script automates building the mpas-bundle repository, running tests
via the site's PBS system (qsub/qstat), and assembling HTML results to be
published on the project web site.

Notes:
- This is a near-line-for-line semantic translation of the original bash
  script. It invokes the same external commands (ssh, scp, qsub, qstat,
  git, etc.) and therefore must be run on a system where those tools are
  available and configured.
- The script attempts to preserve behavior but does not attempt to re-implement
  the PBS system locally; it shells out to the same commands the original
  script used.

Usage: see `main()` argparse help. Typical invocation mirrors the original
shell script flags.
"""

from __future__ import annotations

import argparse
import datetime
import errno
import fcntl
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


TIMESTAMP = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")
LOCK_FILE_NAME = "mpas_bundle_cron.lock"
LOGFILE = None
HTML_BODY_FILE = None


def init_logs(cron_logdir: str) -> None:
    """Create a log directory and initialize the global log file and HTML body file.

    Args:
        cron_logdir: Path to directory where logs and temporary html will be stored.
    """
    global LOGFILE, HTML_BODY_FILE
    p = Path(cron_logdir)
    p.mkdir(parents=True, exist_ok=True)
    LOGFILE = str(p / f"mpas-bundle-cron.log.{TIMESTAMP}")
    # ensure logfile exists
    Path(LOGFILE).touch()
    HTML_BODY_FILE = str(p / "body.html")


def log(message: str) -> None:
    """Log a message to stdout and append it to the logfile (if available).

    Args:
        message: Message to log (a newline will be appended by this function).
    """
    msg = f"{message}\n"
    if LOGFILE and Path(LOGFILE).exists():
        # append to logfile and also print to stdout
        with open(LOGFILE, "a") as f:
            f.write(msg)
    # always print
    sys.stdout.write(msg)
    sys.stdout.flush()


def remove_lock(lockfile: str) -> None:
    """Remove the lock file if it exists.

    Args:
        lockfile: Path to the lock file.
    """
    try:
        Path(lockfile).unlink()
    except FileNotFoundError:
        pass


def another_instance(lockfile: str) -> None:
    """Log that another instance is running and exit.

    Args:
        lockfile: Path to the lock file that could not be acquired.
    """
    log(f"Cannot acquire lock on {lockfile}")
    log("There is another instance running, exiting")
    sys.exit(1)


def acquire_lock(lockfile: str, max_age_seconds: int = 72000) -> None:
    """Acquire a simple pid-based lockfile.

    This implementation is intentionally lightweight: if the lock file exists
    and its modification time is less than `max_age_seconds` old, we assume
    another instance is running and exit. Otherwise we create/overwrite the
    lock file with the current PID. The original script used the `lockfile`
    utility with retries; this function does not retry and will fail-fast.

    Args:
        lockfile: Path to the lock file.
        max_age_seconds: Age in seconds after which an existing lock file is
            considered stale and will be replaced.
    """
    lf = Path(lockfile)
    if lf.exists():
        age = time.time() - lf.stat().st_mtime
        if age < max_age_seconds:
            another_instance(lockfile)
        else:
            # stale lock, remove it
            try:
                lf.unlink()
            except Exception:
                another_instance(lockfile)

    # create lock file containing PID
    lf.write_text(str(os.getpid()))


def run_command(cmd: str, check: bool = False, capture: bool = False, shell: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command, log it, and return the CompletedProcess.

    Args:
        cmd: Command string to run (passed to the shell by default).
        check: If True, raise CalledProcessError on non-zero exit status.
        capture: If True, capture stdout+stderr and return them in the CompletedProcess.
        shell: Whether to run the command through the shell.
    """
    log(cmd)
    if capture:
        return subprocess.run(cmd, shell=shell, check=check, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    else:
        return subprocess.run(cmd, shell=shell, check=check)


def check_pbs_return(jobno: str) -> int:
    """Check PBS job exit status via `qstat -x -f`.

    Returns the integer exit status of the job if available, otherwise 1.

    Args:
        jobno: PBS job identifier.
    """
    try:
        cp = run_command(f"QSCACHE_BYPASS=1 qstat -x -f {jobno} | grep 'Exit_status'", capture=True)
        out = cp.stdout.strip() if cp.stdout else ""
        log(f"jobno={jobno} pbs_status={out}")
        if out:
            # expected format: "\tExit_status = <num>"
            parts = out.split()
            if parts:
                # last part should be the numeric code
                try:
                    code = int(parts[-1])
                    return code
                except ValueError:
                    return 1
        return 1
    except subprocess.CalledProcessError:
        return 1


def queue_wait(job: str, pcode: int, secs: int) -> None:
    """Wait for a job to appear (pcode=1) or disappear (pcode=0) from the PBS queue.

    Args:
        job: PBS job id.
        pcode: 1 to wait until the job appears, 0 to wait until it leaves.
        secs: Sleep seconds between checks.
    """
    # qstat returns 0 when job exists; non-zero when it does not
    rc = subprocess.run(f"qstat {job}", shell=True).returncode
    log(f"queue_wait started job={job} pcode={pcode} rc={rc}")
    if pcode > 0:
        while rc > 0:
            time.sleep(secs)
            rc = subprocess.run(f"qstat {job}", shell=True).returncode
    else:
        while rc == 0:
            time.sleep(secs)
            rc = subprocess.run(f"qstat {job}", shell=True).returncode
    log(f"queue_wait finished job={job} pcode={pcode} rc={rc}")


def print_header(outfile: str) -> None:
    """Write the HTML header and table header to `outfile`.

    Args:
        outfile: Path to the HTML file to create/append header to.
    """
    html_header = [
        "<!DOCTYPE html> <html> <head> <style>",
        "table { font-family: arial, sans-serif; border-collapse: collapse; width: 100%; }",
        "td, th { border: 1px solid #dddddd; text-align: left; padding: 8px; }",
        "th { top:0; position:sticky; background-color:white; border: 1px solid black; }",
        "tr:nth-child(even) { background-color: #dddddd; } </style> </head>",
        "<body> <h2>mpas-bundle mpas-jedi ctest results</h2>",
        "<table> <tr> <th>Date</th> <th>Results</th> <th>Spack</th> <th>CC </th> <th>Tools</th> <th>Stats</th></tr>",
    ]
    with open(outfile, "w") as f:
        for line in html_header:
            f.write(line + "\n")


def print_footer(outfile: str) -> None:
    """Write the HTML footer and year indices to `outfile`.

    Args:
        outfile: Path to the HTML file to append footer to.
    """
    with open(outfile, "a") as f:
        f.write("</table><table> <tr> <th><h2>Year</h2></th>\n")
        f.write("<tr><td> 2025 </td> <td><a href=2025/index.html>2025 test results</a> </td> </tr>\n")
        f.write("<tr><td> 2024 </td> <td><a href=2024/index.html>2024 test results</a> </td> </tr>\n")
        f.write("<tr><td> </td> </tr>\n")
        f.write("</table> </body> </html>\n")


def run_cmake(build_dir: str, bundle_dir: str, cc: str, dbl_p: str, build_type: str, log_dir: str) -> None:
    """Create a small remote script to run cmake on the Derecho login node and execute it via ssh.

    Args:
        build_dir: Directory where the build should be performed.
        bundle_dir: Path to the mpas-bundle source.
        cc: Compiler toolchain name (gnu/intel/nvhpc).
        dbl_p: 'ON' or 'OFF' indicating double precision.
        build_type: CMake build type (Release/Debug/...)
        log_dir: Directory where temporary scripts and logs are stored.
    """
    cmake_script = Path(log_dir) / "run_cmake.sh"
    cmake_content = f"""#!/bin/bash
cd {build_dir} && source {bundle_dir}/env-setup/{cc}-derecho.sh && source {bundle_dir}/env-setup/ioda-modules.list && if [ -f Makefile ]; then echo \"make update\" && make update |& tee make.update.log; fi && cmake -DCMAKE_VERBOSE_MAKEFILE=ON -DBUNDLE_SKIP_RTTOV=ON -DMPAS_DOUBLE_PRECISION={dbl_p} -DBUILD_IODA_CONVERTERS=ON -DCMAKE_BUILD_TYPE={build_type} ctest_update {bundle_dir};
"""
    cmake_script.write_text(cmake_content)
    cmake_script.chmod(0o755)
    run_command(f"ssh derecho.hpc.ucar.edu {cmake_script} |& tee {cmake_script}.log")


def check_git_changes(bundle_dir: str, check_changes_log: str, log_dir: str) -> int:
    """Check remote git repositories for changes.

    This implementation shells out to `ssh` to run a small script on the remote
    Derecho login node (to mirror the original script). It inspects the output
    for indications of updates.

    Returns 1 if changes were found, 0 otherwise.
    """
    # Create the remote check script
    check_script = Path(log_dir) / "check_changes.sh"
    update_file = Path(log_dir) / "files_changed.lock"
    if update_file.exists():
        update_file.unlink()

    check_content = f"""#!/bin/bash -l
dirs=$(ls -d */)
for subdir in $dirs; do
  if [ ! -d "${subdir}/.git" ]; then
    continue
  fi
  cd "${subdir}"
  git fetch >& /dev/null
  branch=$(git rev-parse --abbrev-ref HEAD)
  local_commit=$(git rev-parse --short HEAD)
  remote_commit=$(git rev-parse --short origin/${{branch}})
  if [ "$local_commit" != "$remote_commit" ]; then
    echo "updating ${subdir} to sha $remote_commit"
  fi
  cd ..
done
"""
    check_script.write_text(check_content)
    check_script.chmod(0o755)

    # Run script on remote and capture output
    cp = run_command(f"ssh derecho.hpc.ucar.edu \"bash -s\" < {check_script} |& tee {check_changes_log}", capture=True)
    out = cp.stdout or ""
    # If output contains "updating" then changes were found
    if "updating" in out:
        return 1
    return 0


def get_ctest_summary(logfile: str, make_job: str, ctest_job: str, test_name: str) -> tuple[str, int]:
    """Analyze ctest logs and PBS job status to produce a short summary.

    Returns a tuple (summary_string, return_code) where return_code==0 means success.
    """
    log(f"get_ctest_summary() logfile={logfile} test_name={test_name}")
    if not Path(logfile).exists():
        make_rc = check_pbs_return(make_job)
        if make_rc != 0:
            lsummary = f"make job failed return code {make_rc}"
        else:
            ctest_rc = check_pbs_return(ctest_job)
            if ctest_rc != 0:
                lsummary = f"{test_name} failed {ctest_rc}"
            else:
                lsummary = f"{test_name} didn't run"
        return (lsummary, 1)
    # otherwise try to extract summary from logfile
    try:
        out = subprocess.check_output(f"egrep 'tests .*passed' {logfile} | awk '{{printf \"%s %s\\n\", $1, $3}}'", shell=True, text=True)
        lsummary = f"{test_name} {out.strip()}"
        return (lsummary, 0)
    except subprocess.CalledProcessError:
        return (f"{test_name} run didn't complete", 1)


def run_ctests(scripts: str, cc: str, make_job: str, timestamp: str, build_type: str) -> tuple[str, str, str]:
    """Run ctests by submitting PBS jobs and wait for completion.

    Returns a tuple (html_results, mpas_ctest_time, ioda_ctest_time).
    """
    global CTEST_LOGFILE, CTEST_IODA_LOGFILE
    # rotate old logs if present
    try:
        (Path('.') / CTEST_LOGFILE).replace(Path('.') / f"{CTEST_LOGFILE}.old")
    except Exception:
        pass
    try:
        (Path('.') / CTEST_IODA_LOGFILE).replace(Path('.') / f"{CTEST_IODA_LOGFILE}.old")
    except Exception:
        pass

    run_command(f"{scripts}/run_make.bundle.sh -A {ACCOUNT} -q {QUEUE} -p economy -x ctest -c {cc} -N \"cron-{cc}-ctest-{build_type}\" -m -n")
    res = subprocess.run("qsub -W depend=afterok:${make_job} ./ctest.pbs.sh", shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        log("cannot connect to Derecho PBS")
        sys.exit(1)
    ctest_job = res.stdout.strip()

    run_command(f"{scripts}/run_make.bundle.sh -A {ACCOUNT} -q {QUEUE} -p economy -x ctest-ioda -c {cc} -N \"cron-{cc}-ctest-{build_type}\" -m -n")
    res2 = subprocess.run("qsub -W depend=afterok:${make_job} ./ctest-ioda.pbs.sh", shell=True, capture_output=True, text=True)
    if res2.returncode != 0:
        log("cannot connect to Derecho PBS")
        sys.exit(1)
    ctest_ioda_job = res2.stdout.strip()

    # wait for the ctest job to show up
    queue_wait(ctest_job, 1, 5)
    # wait for ctest job to finish
    queue_wait(ctest_job, 0, 60)

    # get runtimes
    mpas_ctest_time = subprocess.run(f"qstat -xf {ctest_job} | grep used.walltime | awk '{{print $3}}'", shell=True, capture_output=True, text=True).stdout.strip() or "NA"
    ioda_ctest_time = subprocess.run(f"qstat -xf {ctest_ioda_job} | grep used.walltime | awk '{{print $3}}'", shell=True, capture_output=True, text=True).stdout.strip() or "NA"

    lmpas_summary, ret1 = get_ctest_summary(CTEST_LOGFILE, make_job, ctest_job, "mpas-ctest")
    if ret1 != 0:
        lmpas_href = ""
        mpas_ctest_time = "NA"
    else:
        lmpas_href = f'href="./results/ctest.results.log.{timestamp}"'

    lioda_summary, ret2 = get_ctest_summary(CTEST_IODA_LOGFILE, make_job, ctest_ioda_job, "ioda-ctest")
    if ret2 != 0:
        lioda_href = ""
        ioda_ctest_time = "NA"
    else:
        lioda_href = f'href="./results/ctest-ioda.results.log.{timestamp}"'

    html_results = f"<td><a {lmpas_href}>{lmpas_summary}</a> -- <a {lioda_href}>{lioda_summary}</a> </td>"
    return (html_results, mpas_ctest_time, ioda_ctest_time)


def make_html(dest_dir: str, make_job: str, cc: str, timestamp: str, mpas_ctest_time: str, ioda_ctest_time: str, summary: str, sha_file: str, build_type: str) -> None:
    """Build the `index.html` page, copy results to the remote host, and rotate older files.

    Args mirror the original shell function. External commands (`scp`, `ssh`) are
    used to transfer files to the remote web host.
    """
    log(f"make_html() dest_dir: {dest_dir} make_job={make_job} mpas_ctest_time={mpas_ctest_time}")
    bld = "Release"
    if build_type == "Debug":
        bld = build_type
    elif build_type == "RelWithDebInfo":
        bld = "Rel-Deb"

    # Attempt to find tool versions from env-setup scripts
    spack_stack = "unknown"
    try:
        lines = Path(BUNDLE_DIR) / f"env-setup/{cc}-derecho.sh"
        # this is a rough translation: keep the grep/awk behavior simple
        spack_stack = subprocess.run(f"grep spack-stack- {lines} | awk -F/ '{{print $8}}' | awk -F- '{{print $3}}'", shell=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        spack_stack = "unknown"

    comp = "gcc" if cc == "gnu" else ("intel" if cc == "intel" else "nvhpc")
    compiler = subprocess.run(f"grep \"load .*{comp}\" {BUNDLE_DIR}/env-setup/{cc}-derecho.sh | awk '{{print $3}}' | awk -F- '{{print $2}}'", shell=True, capture_output=True, text=True).stdout.strip()
    mpich = subprocess.run(f"grep \"load .*cray-mpich\" {BUNDLE_DIR}/env-setup/{cc}-derecho.sh | awk '{{print $3}}' | awk -F- '{{print $3}}'", shell=True, capture_output=True, text=True).stdout.strip()

    make_time = subprocess.run(f"qstat -xf {make_job} | grep used.walltime | awk '{{print $3}}'", shell=True, capture_output=True, text=True).stdout.strip() or "NA"

    stats = f"<a href=./shas/{Path(sha_file).name}> Q:{QUEUE.split('@')[0]} make:{make_time} mpas_ctest:{mpas_ctest_time} ioda_ctest:{ioda_ctest_time} </a>"
    # prepend current result
    with open("body.html", "w") as f:
        f.write(f"<tr><td>{timestamp}</td> {summary} <td>{spack_stack}</td> <td>{cc}</td> <td>{bld} {compiler} {mpich}</td> <td>{stats}</td> ")
        f.write("\n")
        if Path(HTML_BODY_FILE).exists():
            with open(HTML_BODY_FILE, "r") as old:
                f.write(old.read())
    shutil.copy("body.html", HTML_BODY_FILE)

    # assemble index.html
    if Path("index.html").exists():
        Path("index.html").unlink()
    print_header("index.html")
    with open("index.html", "a") as indexf:
        with open("body.html", "r") as bodyf:
            indexf.write(bodyf.read())
    print_footer("index.html")
    Path("body.html").unlink()

    host = "eris.mmm.ucar.edu"
    dest = f"{host}:{dest_dir}"

    if Path(CTEST_LOGFILE).exists():
        resultsfile = f"ctest.results.log.{timestamp}"
        subprocess.run(f"echo {timestamp} > {resultsfile}", shell=True)
        subprocess.run(f"egrep -A 20 'Test|Start' {CTEST_LOGFILE} >> {resultsfile}", shell=True)
        log(f"scp ./{resultsfile} {dest}/results/")
        subprocess.run(f"scp ./{resultsfile} {dest}/results/", shell=True)
        Path(resultsfile).replace(Path(f"ctest.results.log.old"))
    else:
        log(f"{CTEST_LOGFILE} doesn't exist")

    if Path(CTEST_IODA_LOGFILE).exists():
        resultsfile = f"ctest-ioda.results.log.{timestamp}"
        subprocess.run(f"echo {timestamp} > {resultsfile}", shell=True)
        subprocess.run(f"egrep -A 20 'Test|Start' {CTEST_IODA_LOGFILE} >> {resultsfile}", shell=True)
        log(f"scp ./{resultsfile} {dest}/results/")
        subprocess.run(f"scp ./{resultsfile} {dest}/results/", shell=True)
        Path(resultsfile).replace(Path(f"ctest-ioda.results.log.old"))
    else:
        log(f"{CTEST_IODA_LOGFILE} doesn't exist")

    log(f"scp {sha_file} {dest}/shas")
    subprocess.run(f"scp {sha_file} {dest}/shas", shell=True)

    # rotate/publish
    run_command(f"ssh {host} \"cd {dest_dir} && tar --remove-files -rf index.tar index.2*\"")
    Path(f"index.{TIMESTAMP}.html").write_text(Path("index.html").read_text())
    run_command(f"scp ./index.{TIMESTAMP}.html {dest}")
    Path(f"index.{TIMESTAMP}.html").unlink()
    run_command(f"ssh {host} \"cd {dest_dir} && rm -f index.html && ln -s index.{TIMESTAMP}.html index.html\"")


# Global defaults translated from the original script
CTEST_LOGFILE = "ctest.pbs.sh.log"
CTEST_IODA_LOGFILE = "ctest-ioda.pbs.sh.log"
MAIN_Q = "main@desched1"
PREEMPT_Q = "preempt@desched1"
DEV_Q = "develop@desched1"
QUEUE = MAIN_Q
BUNDLE_DIR = ""
BUILD_DIR_ROOT = ""
tools = ""
precision = "2"
force_build = False
LOG_DIR = str(Path.home() / "my_cron_logs")
run_cmake_flag = True
suffix = ""
ACCOUNT = "nmmm0015"
build_type = "Release"


def build_and_test(cc: str, dbl_p: str, html_dir: str, run_cmake_arg: bool, sha_file: str, build_type_arg: str, suffix_arg: str) -> None:
    """High-level function to perform build and test for a given compiler/toolchain.

    This mirrors the `build_and_test` bash function: creates build directories,
    optionally runs cmake remotely, submits make via the helper script, and
    conditionally runs ctests for double precision builds.
    """
    build_dir_suffix = "2p" if dbl_p == "ON" else "1p"
    build_dir = Path(BUILD_DIR_ROOT) / f"build-{cc}-{build_dir_suffix}"
    if suffix_arg:
        build_dir = Path(str(build_dir) + f"_{suffix_arg}")
    if build_type_arg != "Release":
        build_dir = Path(str(build_dir) + f"_{build_type_arg}")

    build_dir.mkdir(parents=True, exist_ok=True)
    log(f"BUNDLE_DIR {BUNDLE_DIR}")
    log(f"BUILD_DIR {build_dir}")
    os.chdir(build_dir)
    log(f"building in: {os.getcwd()}")

    if run_cmake_arg:
        log(f"run_cmake {build_dir} {BUNDLE_DIR} {cc} {dbl_p} {build_type_arg}")
        run_cmake(str(build_dir), BUNDLE_DIR, cc, dbl_p, build_type_arg, LOG_DIR)

    scripts = Path(BUNDLE_DIR) / "env-setup"
    # rotate logs
    try:
        if Path("make.pbs.sh.log").exists():
            Path("make.pbs.sh.log").replace(Path("make.pbs.sh.log.old"))
    except Exception:
        pass

    run_command(f"{scripts}/run_make.bundle.sh -A {ACCOUNT} -q {QUEUE} -p economy -x make -c {cc} -N \"cron-{cc}-make-{build_type_arg}\" -m -n")
    res = subprocess.run("qsub make.pbs.sh", shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        log("cannot connect to Derecho PBS")
        sys.exit(1)
    make_job = res.stdout.strip()
    log(f"{cc} make: {make_job}")

    mpas_ctest_time = "NA"
    ioda_ctest_time = "NA"
    summary = ""

    if dbl_p == "ON":
        html_results, mpas_ctest_time, ioda_ctest_time = run_ctests(str(scripts), cc, make_job, TIMESTAMP, build_type_arg)
        summary = html_results
        log(f"build_and_test() summary:{summary} mpas_ctest_time:{mpas_ctest_time} ioda_ctest_time:{ioda_ctest_time}")
    else:
        queue_wait(make_job, 1, 5)
        queue_wait(make_job, 0, 60)
        summary = "Single precision build - no ctests run"
        make_rc = check_pbs_return(make_job)
        if make_rc == 0:
            build_dir_root = str(build_dir).split("_")[0]
            latest_dir = f"{build_dir_root}_latest"
            try:
                Path(latest_dir).unlink()
            except Exception:
                pass
            os.symlink(os.getcwd(), latest_dir)
        else:
            summary = f"single precision make job failed return code {make_rc}"

    log(f"calling make_html() dir: {html_dir} make_job {make_job} mpas_ctest_time {mpas_ctest_time} ioda_ctest_time {ioda_ctest_time} cc {cc} timestamp {TIMESTAMP} summary {summary}")
    make_html(html_dir, make_job, cc, TIMESTAMP, mpas_ctest_time, ioda_ctest_time, summary, sha_file, build_type_arg)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments mirroring the original shell script flags."""
    p = argparse.ArgumentParser(description="Build mpas-bundle and run mpas-jedi ctests")
    p.add_argument("-d", dest="bundle_dir", help="where the mpas-bundle repo has been cloned to")
    p.add_argument("-b", dest="build_dir_root", help="base directory for builds")
    p.add_argument("-q", dest="queue", default=MAIN_Q, help="queue to use")
    p.add_argument("-a", dest="account", default=ACCOUNT, help="PBS account")
    p.add_argument("-p", dest="precision", default="2", help="1 or 2")
    p.add_argument("-t", dest="build_type", default="Release", help="CMake build type")
    p.add_argument("-c", dest="tools", help="compiler: gnu,intel,nvhpc,or all")
    p.add_argument("-l", dest="lock_file", help="absolute path to lock file")
    p.add_argument("-o", dest="out_dir", default="/web/htdocs/projects/mpas-jedi/weekly-ctests", help="where html files will be copied to")
    p.add_argument("-x", dest="suffix", help="suffix to add to the build directory")
    p.add_argument("-f", dest="force_build", action="store_true", help="force build even if no source changed")
    p.add_argument("-n", dest="no_cmake", action="store_true", help="don't run cmake")
    return p.parse_args()


def main() -> None:
    global BUNDLE_DIR, BUILD_DIR_ROOT, QUEUE, tools, precision, force_build, LOG_DIR, run_cmake_flag, suffix, ACCOUNT, build_type
    args = parse_args()

    init_logs(LOG_DIR)
    log(f"commandline: {' '.join(sys.argv)}")

    if not args.bundle_dir:
        log("source dir -d source_dir is required")
        sys.exit(1)
    BUNDLE_DIR = args.bundle_dir
    if not Path(BUNDLE_DIR).is_dir():
        log(f"source dir {BUNDLE_DIR} does not exist")
        sys.exit(1)

    BUILD_DIR_ROOT = args.build_dir_root or str(Path(BUNDLE_DIR).parent)
    if not Path(BUILD_DIR_ROOT).is_dir():
        log(f"output dir {BUILD_DIR_ROOT} does not exist")
        sys.exit(1)

    QUEUE = args.queue
    if QUEUE not in (MAIN_Q, PREEMPT_Q, DEV_Q):
        log(f"queue \"{QUEUE}\" is invalid")
        sys.exit(1)

    tools = args.tools
    if not tools:
        log("compiler -c compiler is required")
        sys.exit(1)

    precision = args.precision
    dbl_precision = "ON" if precision == "2" else "OFF"
    force_build = args.force_build
    run_cmake_flag = not args.no_cmake
    suffix = args.suffix or ""
    ACCOUNT = args.account
    build_type = args.build_type

    log(f"q:{QUEUE} precision: {precision} {dbl_precision} force: {force_build}")

    lock_file = args.lock_file or str(Path(BUNDLE_DIR) / LOCK_FILE_NAME)
    acquire_lock(lock_file)
    try:
        log(f"lockfile: {lock_file}")
        log(f"[{TIMESTAMP}]: Running {sys.argv[0]} on {os.uname().nodename}\n\tfrom {os.getcwd()}\n\tscriptdir={Path(__file__).parent}")

        sha_file = str(Path(LOG_DIR) / f"git_shas.{TIMESTAMP}")
        git_changes = check_git_changes(BUNDLE_DIR, str(Path(LOG_DIR) / "check_changes.log"), LOG_DIR)
        log(f"check_git_changes returned {git_changes}")

        if not force_build and git_changes == 0:
            log("no source changes, not running")
            return

        log(f"building with tools {tools}")
        if tools in ("gnu", "all"):
            build_and_test("gnu", dbl_precision, args.out_dir, run_cmake_flag, sha_file, build_type, suffix)
        if tools in ("intel", "all"):
            build_and_test("intel", dbl_precision, args.out_dir, run_cmake_flag, sha_file, build_type, suffix)
        if tools in ("nvhpc", "all"):
            build_and_test("nvhpc", dbl_precision, args.out_dir, run_cmake_flag, sha_file, build_type, suffix)
    finally:
        remove_lock(lock_file)


if __name__ == "__main__":
    main()
