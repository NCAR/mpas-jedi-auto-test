# mpas-jedi-auto-test
This software is licensed under the terms of the Apache Licence Version 2.0
which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.

This is a set of scripts, etc for automatically building [JCSDA/mpas-bundle](https://github.com/JCSDA/mpas-bundle), running [JCSDA/mpas-jedi](https://github.com/JCSDA/mpas-jedi) ctests, and running [NCAR/MPAS-Workkflow](https://github.com/NCAR/MPAS-Workflow) cylc tests

These scripts are meant to run in concert, in order to coordinate software build, test execution, results post processing, and output formatting for display by a web server. 

## Files

1. `crontab.sh` A crontab table to be installed on a cron enabled machine, e.g. `cron.hpc.ucar.edu`.
1. `mpas-bundle-cron.sh` A script which will build the mpas-bundle package. It can be invoked from cron or run manually. After a successful build it will run the mpas-jedi ctests. This uses `run_make.bundle.sh` found in the [JCSDA/mpas-bundle](https://github.com/JCSDA/mpas-bundle) repository.
1. `run_cylc.sh` A script which will run cylc scenarios, as well as create comparison graphs between different runs of the scenarios. This uses `Run.py` found in the [NCAR/MPAS-Workkflow](https://github.com/NCAR/MPAS-Workflow) repository. This uses `SpawnAnalyzeStats.py` found in the [JCSDA/mpas-jedi](https://github.com/JCSDA/mpas-jedi) repository.
1. `make_spack.sh` A script to build JCSDA/spack-stack. It can be invoked from cron or run manually. This script only builds the packages, two additional steps are required to finish an install. See the [Create lua and Create meta-module steps here](https://github.com/jcsda/spack-stack/wiki/New-and-chained-environments-for-existing-sites)
1. `web/index.php` The main php for displaying MPAS-Workflow cylc results from a web server.
1. `web/listgraphs.php` This traverses a hierarchy of files and displays MPAS-Workflow cylc comparison graphs.
1. `web/inc-*` a set of support files for displaying a stylized table.
1. `web/notes.html` A set of notes describing various aspects of comprison graphs from MPAS-Workflow cylc runs.
