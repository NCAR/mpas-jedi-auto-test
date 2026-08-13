#!/bin/bash 

LOGFILE=""
LOG_DIR="$HOME/my_cron_logs"

init_logs()
{
  local logdir="$1"
  local logbase="$2"
  local timesuffix="$(date +%F-%H)"
  LOGFILE="${logdir}/${logbase}.${timesuffix}"
  mkdir -p ${logdir} || exit 1
  touch $LOGFILE
}

log()
{
  if [ -f "${LOGFILE}" ]; then
    echo -e "$1" | tee -a ${LOGFILE}
  else
    echo -e "$1"
  fi
}

usage()
{
  local args="-d <repository_dir> [-c <branch> ] [-l log_dir] [-h]"
  log "usage:"
  log "  update-repo.sh ${args}"
  log "    -d <repository_dir> is where the repository has been cloned to"
  log "    -c <branch> checkout the provided branch after updating the local sandbox"
  log "    -l <log_dir> the directory to put logfile in, default is $LOG_DIR"
  log "    -h print this help and exit"
  exit 1
}

main()
{
  local repo_dir=""
  declare -r logfile_base="cron.log"
  local checkout=""
  local branch=""
  local help=""

  while getopts d:l:b:h flag
  do
    case "${flag}" in
      d) repo_dir="${OPTARG}";;
      l) LOG_DIR=${OPTARG};;
      b) branch=${OPTARG};;
      h) help="help";;
    esac
  done

  if [ "$help" != "" ]; then
    usage
  fi

  init_logs $LOG_DIR $logfile_base
  log "$(date) commandline: $0 $*"

  if [ "$repo_dir" == "" ]; then
    log "repository_dir is required"
    usage
  fi


  cd ${repo_dir} || { log "cannot cd ${repo_dir}"; exit 1; }
  git fetch -p >> $LOGFILE 2>&1

  if [ "$checkout" != "" ]; then
    if [ "$branch" == "" ]; then
      log "repository is needed when specifying checkout"
      usage
    fi
    git checkout $branch >> $LOGFILE 2>&1 
  fi

  git pull >> $LOGFILE 2>&1

  exit 0
}

main "$@"

