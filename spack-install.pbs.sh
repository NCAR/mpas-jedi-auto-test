#!/usr/bin/env bash

#PBS -l walltime=04:00:00
#PBS -o ./log.install
#PBS -e ./log.install.err
#PBS -j oe
#PBS -k eod
#--- get 1 cpu per thread
##PBS -l select=1:ncpus=128:mem=256GB
#PBS -l select=1:ncpus=64:mem=128GB
#PBS -l job_priority=economy
#--- 
#PBS -N spack-install-2
#PBS -A nmmm0015
##PBS -q main
#PBS -q develop
#

echo "pwd:`pwd`"
date

# assume cwd is in <repo-base>/envs/<env>
source ../../setup.sh
spack env activate .

echo "spack install"
#spack install
#spack install --concurrent-packages=2 --jobs=128
spack install --concurrent-packages=2 --jobs=64
echo "spack install complete"

