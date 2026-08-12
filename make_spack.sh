#!/bin/bash -l

# build spack stack

declare -r timestamp="$(date +%F-%H-%M)"
#declare -r timestamp="$(date +%F-%H)"
declare -r gcc="gcc-13.3.1"
declare -r oneapi="oneapi-2025.3.1"

LOGFILE=""
init_log()
{
  local logdir="$1"
  local compiler="$2"
  mkdir -p ${logdir} || exit 1
  LOGFILE="${logdir}/log.${compiler}.${timestamp}"
  touch $LOGFILE
  echo "LOGFILE:$LOGFILE"
}

log()
{
  if [ -f "${LOGFILE}" ]; then
    echo -e "$1" | tee -a ${LOGFILE}
  else
    echo -e "$1"
  fi
}

log_cmd()
{
  cmd=$i
  log "$cmd"
  #$cmd &> $LOGFILE || log "$cmd failed" && exit 1
  $cmd &> $LOGFILE 
}

usage()
{
  args="-d <build_dir> [-c <compiler>] [-g] [-i] [-l <log_dir>] [-h]"
  log "usage:"
  log "  make_spack.sh ${args}"
  log "    -d <build_dir> is where the spack-stack repo is (or will be cloned to)"
  log "    -c <compiler> is one of $gcc or $oneapi, default is $gcc"
  log "    -g runs git, otherwise assume the repo is cloned and up to date"
  log "    -i only runs install. skips creating the env and concretizing"
  log "    -l log_dir where to put log files, default is <build_dir>"
  log "    -h prints help and exits"
  exit
}

git_clone_or_fetch()
{
  if [ ! -d "./${repo}" ]; then
    log "git clone $repo_url --recurse-submodules"
    git clone $repo_url --recurse-submodules &>> $LOGFILE
    cd ./${repo}
  else
    cd ./${repo}
    if [ ! -d "./.git" ]; then
      log "${repo_dir}/${repo} has no .git"
      exit 1
    fi
    log "git fetch --recurse-submodules "
    git fetch --recurse-submodules &>> $LOGFILE
    log "git pull --recurse-submodules"
    git pull --recurse-submodules &>> $LOGFILE
  fi
}

concretize()
{
  log "spack concretize --force --fresh &> log.concretize ... "
  spack concretize --force --fresh &> log.concretize 
  log "spack concretize finished"
}

main()
{

  #local repo_dir="/glade/derecho/scratch/jwittig/repos-s/spack-stack-dev"
  declare -r script_repo_dir="/glade/work/jwittig/repos1/mpas-jedi-auto-test"
  local repo_dir=""
  local repo="spack-stack"
  local repo_url="https://github.com/JCSDA/spack-stack.git"

  local compiler=$gcc
  echo "compiler:$compiler"

  local site="derecho"
  local template="unified-dev"

  local log_dir=""
  local git=""
  local install_only=""
  local help=""

  while getopts c:d:l:gih flag
  do
    case "${flag}" in
      c) compiler="${OPTARG}";;
      d) repo_dir="${OPTARG}";;
      l) log_dir="${OPTARG}";;
      g) git="true";;
      i) install_only="true";;
      h) help="help";;
    esac
  done

  if [ "$help" != "" ]; then
    usage
  fi

  # the root build dir is required
  if [ "$repo_dir" == "" ]; then
    log "-d <build_dir> is required"
    usage
  fi

  mkdir -p $repo_dir 
  if [ "$log_dir" == "" ]; then
    log_dir=$repo_dir
  fi
  init_log $log_dir $compiler
  log "commandline: $0 $*"
  local hname="$(hostname)"
  log "running on $hname in $repo_dir"


  # go to the build directory and clone/update the repository
  cd $repo_dir

  if [ "$git" != "" ]; then
    git_clone_or_fetch
  fi

  cd ${repo_dir}/${repo}
  log "sourcing setup.sh"
  source setup.sh &>> $LOGFILE

  # create a new env
  local name="ue-${compiler}"
  if [ "$install_only" == "" ]; then
    if [ -d "envs/${name}" ]; then
      log "mv envs/${name} envs/${name}.${timestamp}"
      mv envs/${name} envs/${name}.${timestamp}
    fi

    local c_log="log.create-${compiler}"
    log "spack stack create env --site=$site --template=$template --compiler=$compiler --name=$name ..."
    spack stack create env --site=$site --template=$template --compiler=$compiler --name=$name &> $c_log
  else
    log "install_only=$install_only, skipping create env"
  fi

  cd ./envs/$name
  log "running in $(pwd)"
  log "spack env activate . "
  spack env activate . 

  if [ "$install_only" == "" ]; then
    concretize
  else
    log "install_only=$install_only, skipping concretize"
  fi

  # run install in the background redirecting output to a file. It takes hours to run on derecho
  #log "spack install &> log.install &"
  #spack install &> log.install &
  log "running qsub ${script_repo_dir}/spack-install.pbs.sh"
  qsub ${script_repo_dir}/spack-install.pbs.sh

    # 7. spack module lmod refresh 2>&1 tee log.mod-refresh
    # 8. spack stack setup-meta-modules 2>&1 | tee log.meta-modules
}

main "$@"
