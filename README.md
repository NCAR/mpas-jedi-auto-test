# mpas-jedi-auto-test
This software is licensed under the terms of the Apache Licence Version 2.0
which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.

This is a set of scripts, etc for automatically building [JCSDA/mpas-bundle](https://github.com/JCSDA/mpas-bundle), running [JCSDA/mpas-jedi](https://github.com/JCSDA/mpas-jedi) ctests, and running [NCAR/MPAS-Workkflow](https://github.com/NCAR/MPAS-Workflow) cylc tests

These scripts are meant to run in concert, in order to coordinate software build, test execution, results post processing, and output formatting for display by a web server. 

## Files

1. `crontab.sh` A crontab table to be installed on a cron enabled machine, e.g. cron.hpc.ucar.edu.
2. `mpas-bundle-cron.sh` A script which will build the mpas-bundle package. It can be invoked from cron or run manually. After a successful build it will run the mpas-jedi ctests.
3. `run_cylc.sh` A script which will run cylc scenarios, as well as create comparison graphs between different runs of the scenarios.
4. `body.html' The base html file for appending mpas-jedi ctest results to. This will get copied to a web server.
5. `web/index.php` The main php for displaying MPAS-Workflow cylc results from a web server.
6. `web/listgraphs.php` This traverses a hierarchy of files and displays MPAS-Workflow cylc comparison graphs.
7. `web/inc-*` a set of support files for displaying a stylized table.
8. `web/notes.html` A set of notes describing various aspects of comprison graphs from MPAS-Workflow cylc runs.
