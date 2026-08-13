
# run scripts to build mpas-bundle and run ctest
# to use this, 
# 1. log on to cron.hpc.ucar.edu
# 2. run: crontab crontab.sh

# the base directory for log files
log_dir=~/my_cron_logs

# set this to the directory the mpas-bundle repository has been cloned to
# don't put it on scratch or it will get corrupted due to scratch retention policy
bundle_dir=/glade/work/jwittig/repos1/mpas-bundle-cron-src/mpas-bundle
# set this to where the builds are - we want them on scratch so they get cleaned up
builds_dir=/glade/derecho/scratch/jwittig/repos-s/mpas-bundle-cron/
# the directory where the single precision bundle build is
bundle_build_dir="'/glade/derecho/scratch/jwittig/repos-s/mpas-bundle-cron/build-gnu-1p_[0-9][0-9]'"

# this is the location of the scripts
script_dir=/glade/work/jwittig/repos1/mpas-jedi-auto-test
# the script which builds mpas-bundle
build_script=mpas-bundle-cron.sh
# the script which runs a cylc job or creates graphs
workflow_script=run_cylc.sh

# the workflow directory with the cylc configurations and experiment scenarios
workflow_dir=/glade/work/jwittig/repos1/MPAS-Workflow-cron

# the workflow scenario to run, relative to the workflow directory
workflow_scenario=scenarios/3denvar_OIE120km_WarmStart_VarBC_cron.yaml
workflow_scenario2=scenarios/3dhybrid_OIE120km_WarmStart_cron.yaml

# the directory with the graphics scripts
graphs_dir=/glade/work/jwittig/repos1/mpas-jedi-cron/graphics
# the directory where the workflow results graphs shold be placed
graphs_out_dir=/glade/derecho/scratch/jwittig/graphs/data/

# derecho hpc
derecho=derecho.hpc.ucar.edu
# mmm web server
webserver=eris.mmm.ucar.edu
# destination for graphs
web_graphs_dir=/net/htdocs/projects/mpas-jedi/weekly-cycling/cylc_graphs

#
# spack stack
#
# the spack-stack build directory
ss_build_dir=/glade/derecho/scratch/jwittig/repos-s/spack-stack-cron
# the compilers to use
ss_gcc=gcc-13.3.1
ss_oneapi=oneapi-2025.3.1
# the spack stack build script
ss_build_script=make_spack.sh
# build both flavors on Saturdays at 1 and 2 am
# these must be run on derecho; they take 6 to 8 hours
#05 01 * * 6 ssh derecho "$script_dir/$ss_build_script -d $ss_build_dir -c $ss_gcc -g"
# don't run git (-n) for the second build, use the repo set up by the first build
#05 02 * * 6 ssh derecho "$script_dir/$ss_build_script -d $ss_build_dir -c $ss_oneapi"


# start at 11:05 PM and clean up log files
05 23 * * 5 ssh $derecho "cd $log_dir && (gunzip mpas-bundle-cron.log.tar.gz ; tar --remove-files -uf mpas-bundle-cron.log.tar mpas-bundle-cron.log.2* ; tar --remove-files -uf mpas-bundle-cron.log.tar git_shas* ; gzip mpas-bundle-cron.log.tar)"

# at 7:30 AM on 7th day of the month clean up last months log files
lastmon=$(date --date='-1 month' +%Y-%m)
30 7 7 * * ssh $derecho "cd $log_dir/cylc/logs && tar --remove-files -czf run_cylc.cron.$lastmon.tgz *.$lastmon*.log"
30 7 7 * * ssh $derecho "mv $log_dir/mpas-bundle-cron.log.tar.gz $log_dir/mpas-bundle-cron.log.$lastmon.tar.gz

bld_suffix=date +%y_%0m_%0d

# start at 12:05 AM on Mon-Fri
# make a double precision build of mpas-bundle and run ctest
# the build script won't do anything if there have been no changes to the
# modules used to create mpas-bundle (unless the '-f' parameter is provided).
05 00 * * 1-5 ssh $derecho "echo $(${bld_suffix}) ${bundle_dir} 'make 2p'  >> $log_dir/cron.log && cd $bundle_dir && git fetch -p >> $log_dir/cron.log ; git status >> $log_dir/cron.log ; git pull >> $log_dir/cron.log" ; ssh $derecho "$script_dir/$build_script -d $bundle_dir -b $builds_dir -q develop@desched1 -c gnu -p 2 -a nmmm0015"

# start at 12:05 AM on Sat 
# always build and run ctests, even if no source change from previous run (-f)
05 00 * * 6 ssh $derecho "$script_dir/$build_script -d $bundle_dir -b $builds_dir -q develop@desched1 -c gnu -p 2 -f -a nmmm0015"
05 02 * * 6 ssh $derecho "$script_dir/$build_script -d $bundle_dir -b $builds_dir -q develop@desched1 -c gnu -p 2 -f -a nmmm0015 -t RelWithDebInfo"
05 03 * * 6 ssh $derecho "$script_dir/$build_script -d $bundle_dir -b $builds_dir -q develop@desched1 -c gnu -p 2 -f -a nmmm0015 -t Debug"

# start at 1:05 AM on Sat 
# always build, even if no source change from previous run (-f)
# single precision (-p 1), to be used for cylc experiment.
# use the date as part of the build directory name, so each week's build is unique.
05 01 * * 6 ssh $derecho "$script_dir/$build_script -d $bundle_dir -b $builds_dir -q develop@desched1 -c gnu -p 1 -f -l $builds_dir/$build_script.lock -x $(${bld_suffix}) -a nmmm0015"

# build gpu enabled MPAS-Model
#20 12 * * 1 ssh $derecho "$script_dir/$build_script -d $bundle_dir -b $builds_dir -q develop@desched1 -c nvhpc -p 1 -f -l $builds_dir/$build_script.lock -x $(${bld_suffix}) -a nmmm0015"

# at 12:05 am on Sun update the develop branch of  MPAS-Workflow repo and run the workflow
suffix=$(date +%F)
#05 00 * * 7 ssh $derecho "echo $suffix 'run workflow in ' $workflow_dir >> $log_dir/cron.log && cd $workflow_dir && git fetch -p >> $log_dir/cron.log 2>&1 && git co develop >> $log_dir/cron.log 2>&1 && git pull >> $log_dir/cron.log 2>&1 && $script_dir/$workflow_script -w $workflow_dir -d $bundle_build_dir -k $builds_dir/$build_script.lock -s $workflow_scenario -x $suffix -l $log_dir/cylc"
05 00 * * 7 ssh $derecho "echo $suffix 'run workflow in ' $workflow_dir >> $log_dir/cron.log && cd $workflow_dir && $script_dir/$workflow_script -w $workflow_dir -d $bundle_build_dir -k $builds_dir/$build_script.lock -s $workflow_scenario -x $suffix -l $log_dir/cylc"
# at 1:05 am on Sun run the 3dhybrid workflow
05 01 * * 7 ssh $derecho "echo $suffix 'run workflow in ' $workflow_dir >> $log_dir/cron.log && cd $workflow_dir && $script_dir/$workflow_script -w $workflow_dir -d $bundle_build_dir -k $builds_dir/$build_script.lock -s $workflow_scenario2 -x $suffix -l $log_dir/cylc"

# run the weekly cylc scenario using a gpu build of MPAS-Model
suffix_gpu=2025-05-30_new
workflow_scenario_gpu=scenarios/3denvar_OIE120km_WarmStart_VarBC_gpu_cron.yaml
#55 15 * * * ssh $derecho "echo $suffix >> $log_dir/cron.log 2>&1 && cd $workflow_dir && git fetch -p >> $log_dir/cron.log 2>&1 && git co develop >> $log_dir/cron.log 2>&1 && git pull >> $log_dir/cron.log && $script_dir/$workflow_script -w $workflow_dir -d $bundle_build_dir -k $builds_dir/$build_script.lock -s $workflow_scenario_gpu -x ${suffix}_gpu -l $log_dir/cylc"

# at 2:05 am Mon-Fri try to graph results from the completed workflow runs
casper=casper.hpc.ucar.edu
05 02 * * 1-5 ssh $casper "$script_dir/$workflow_script -w $workflow_dir -g $graphs_dir -o $graphs_out_dir -m $webserver -c $web_graphs_dir/ -e jwittig@ucar.edu -l $log_dir/cylc"
