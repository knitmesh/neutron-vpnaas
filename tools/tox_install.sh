#!/bin/sh

# Many of neutron's repos suffer from the problem of depending on neutron,
# but it not existing on pypi.

# This wrapper for tox's package installer will use the existing package
# if it exists, else use zuul-cloner if that program exists, else grab it
# from neutron master via a hard-coded URL. That last case should only
# happen with devs running unit tests locally.

# From the tox.ini config page:
# install_command=ARGV
# default:
# pip install {opts} {packages}

set -x

exec > /tmp/tox_install.txt 2>&1

ZUUL_CLONER=/usr/zuul-env/bin/zuul-cloner
neutron_installed=$(echo "import neutron" | python 2>/dev/null ; echo $?)
NEUTRON_DIR=$HOME/neutron

set -e

install_cmd="pip install"
if [ "$1" = "constrained" ]; then
    install_cmd="$install_cmd $2"
    shift
fi
shift

if [ -d "$NEUTRON_DIR" ]; then
    echo "FOUND Neutron code at $NEUTRON_DIR - using"
    $install_cmd -U -e $NEUTRON_DIR
elif [ $neutron_installed -eq 0 ]; then
    location=$(python -c "import neutron; print(neutron.__file__)")
    echo "ALREADY INSTALLED at $location"
elif [ -x "$ZUUL_CLONER" ]; then
    export ZUUL_BRANCH=${ZUUL_BRANCH-$BRANCH}
    echo "USING ZUUL CLONER to obtain Neutron code"
    cwd=$(/bin/pwd)
    cd /tmp
    $ZUUL_CLONER --cache-dir \
        /opt/git \
        git://git.openstack.org \
        openstack/neutron
    cd openstack/neutron
    $install_cmd -e .
    cd "$cwd"
else
    echo "LOCAL - Obtaining Neutron code from git.openstack.org"
    $install_cmd -U -egit+https://git.openstack.org/openstack/neutron#egg=neutron
fi

$install_cmd -U $*
exit $?
