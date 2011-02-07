#! /usr/bin/env bash

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.

# You should create a ~/.httpovclient/prefs containing at least a
# HP_SERVER="<theserver>" entry.

# These settings can be overridden in ~/.httpovclient/prefs

HP_SERVER=""
HP_PASSWORD="flimpaflump"
HP_POV="povray"
HP_VERURL="http://columbiegg.com/httpov/latest/"
HP_VERPER=259200
HP_TRYTIMES=10
HP_GROUP=""

sleepseed=2
sleepmax=300
nicelevel=5

# Read global config

if [ -a /etc/httpovclient.conf ];then
  . /etc/httpovclient.conf
fi

# Startup checks

if [ $(id -u) -eq 0 ];then
  if [ "$HP_USER" != "" ];then
    echo Started as root - changing to "$HP_USER".
    su - "$HP_USER" -c "$0 $@"
    exit
  else
    echo "HTTPov client: Running as root is not supported."
    exit 1
  fi
fi

if [ -a ~/.httpovclient/prefs ];then
  . ~/.httpovclient/prefs
else
  if [ -a ~/_httpovclient/prefs ];then
    . ~/_httpovclient/prefs
  fi
fi

if [ "$1" != "" ];then
  if echo "$1" | grep '^[0-9][0-9]*$' >/dev/null; then
    HP_CID="$1"
  else
    echo "Client ID must be a positive integer."
    exit 1
  fi
else
  HP_CID="$$"
fi

# Client script settings

HP_CLIENT="$(hostname)":"$HP_CID"
HP_VERSION="1.2"
HP_PID="$$"
HP_WD="${TMPDIR:-/tmp}"/httpovclient."$HP_PID"/
HP_CMDFILE="httpovclient.commands"
HP_ABORTFILE="httpovclient.abort"
HP_CURL="curl --retry 10 --connect-timeout 60 "
HP_STDARGS="client=$HP_CLIENT&version=$HP_VERSION"
if [ "$HP_GROUP" != "" ];then
  echo "This client belong to the group '$HP_GROUP'"
  HP_STDARGS=$HP_STDARGS"&cgroup=$HP_GROUP"
fi
HP_ACTIVELOOP=0

sleeptime="$sleepseed"

# Further startup checks

type "$HP_POV" &>/dev/null
if [ $? = 1 ];then
  echo "Povray binary not found."
  abort=1
fi
type curl &>/dev/null
if [ $? = 1 ];then
  echo "curl not found."
  abort=1
fi
type zip &>/dev/null
if [ $? = 1 ];then
  echo "zip not found."
  abort=1
fi
type unzip &>/dev/null
if [ $? = 1 ];then
  echo "unzip not found."
  abort=1
fi
if [ "$HP_SERVER" = "" ];then
  echo "No server specified."
  abort=1
fi
if [ "$abort" = "1" ];then
  echo "Fatal error."
  exit 1
fi

HP_PWD="$(pwd)"

if [ -a "$HP_WD" ];then
  echo Working directory "$HP_WD" already exists.
  echo "Client aborting."
  exit 1
fi

mkdir "$HP_WD"
cd "$HP_WD"

# Function definitions

trap 'hpcleanup' EXIT
trap 'hpabort' TERM INT

function hpcleanup {
  hpactiveloop_kill
  if [ "$HP_PWD" != "" ];then
    cd "$HP_PWD"
    if [ -a "$HP_WD" ];then
      rm -rf "$HP_WD"
    fi
  fi
  echo "HTTPov client exiting."
}

function hpabort {
  touch "$HP_WD$HP_ABORTFILE"
  echo "HTTPov client abort requested."
}

function hpcheckver {
  sinceepoch=$(date +%s)
  sincelast=$(expr $sinceepoch - $lastcheck)
  if [ $sincelast -gt $HP_VERPER ];then
    lastcheck=$sinceepoch
    $HP_CURL -o "$HP_WD$HP_CMDFILE"\
      "$HP_VERURL"?version="$HP_VERSION" &>/dev/null

    IFS="
" commands=( `cat $HP_WD""$HP_CMDFILE 2>/dev/null` )
    unset IFS

    i=0
    while ( [ "${commands[$i]}" != "" ] )
    do

      key="${commands[$i]%%\=*}"
      value="${commands[$i]#*=}"

      if [ "$key" = "clientver" ]; then
        echo
        echo "Latest client available: $value"
        echo "Find out more at $HP_VERURL"
        echo
      fi
    i=$(expr $i + 1)
    done
  fi
}

function hphello {
  $HP_CURL -o "$HP_WD$HP_CMDFILE"\
    "$HP_SERVER/httpov.php?command=hello&$HP_STDARGS"
}

function hpgetjob {
  $HP_CURL -o "$HP_WD$HP_CMDFILE"\
    "$HP_SERVER/httpov.php?command=getjob&$HP_STDARGS" &>/dev/null
}

function hppostbatch {
  fullstart="_frame_"$(printf '%08d' "$startframe")
  if [ "$slice" = "" ];then
    $HP_CURL -o "$HP_WD"upload -F \
      "filedata=@$name$fullstart.zip;filename=$name$fullstart.zip" \
      "$HP_SERVER/httpov.php?command=postbatch&job=$job&batch=$batch&$HP_STDARGS" &>/dev/null
  else
    fullslice="_"$(printf '%04d' "$slice")
    $HP_CURL -o "$HP_WD"upload -F \
      "filedata=@$name$fullstart$fullslice.zip;filename=$name$fullstart$fullslice.zip" \
      "$HP_SERVER/httpov.php?command=postbatch&job=$job&batch=$batch&$HP_STDARGS" &>/dev/null
  fi
}

function hpupsleep {
  local lsleeptime=$(expr $1 + $1)
  if [ $lsleeptime -gt $sleepmax ];then
    lsleeptime=$sleepmax
  fi
  echo $lsleeptime
}

function hpreadcommands {
  IFS="
" commands=( `cat $HP_WD""$HP_CMDFILE 2>/dev/null` )
  unset IFS

  render=0

  i=0
  while ( [ "${commands[$i]}" != "" ] )
  do

    key="${commands[$i]%%\=*}"
    value="${commands[$i]#*=}"

    if [ "$key" = "command" ]; then
      if [ "$value" = "getbatch" ]; then
        hp_sleep=0
        job="${commands[1]#*=}"
        name="${commands[2]#*=}"
        frames="${commands[3]#*=}"
      fi
      if [ "$value" = "sleep" ]; then
        if [ $jobmessage = 1 ]; then
          echo "$(date): Server found, but no job is available."
          jobmessage=0
        fi
      fi
      if [ "$value" = "getjob" ]; then
        job=0
      fi
      if [ "$value" = "render" ]; then
        batch="${commands[1]#*=}"
        startframe="${commands[2]#*=}"
        stopframe="${commands[3]#*=}"
        slice="${commands[4]#*=}"
        startrow="${commands[5]#*=}"
        endrow="${commands[6]#*=}"
        render=1
      fi
    fi
    if [ "$key" = "message" ]; then
      echo Server message: "$value"
    fi

    if [ "$key" = "error" ]; then
      echo Server error: "$value"
      exit 1
    fi

    i=$(expr $i + 1)
  done

  if [ $hp_sleep = 1 ]; then
    hpsleep $sleeptime
    sleeptime=$(hpupsleep $sleeptime)
  fi
}

function hpsleep {

  hpcheckver

  if [ -a $HP_WD""$HP_ABORTFILE ];then
    exit
  fi
  echo "$(date): Sleeping $1 seconds"
  if [ $1 -gt 10 ];then
    sleeps=$(expr $1 / 10)
    remainder=$(expr $1 % 10)
    while ( [ $sleeps -gt 0 ] );do
      if [ -a $HP_WD""$HP_ABORTFILE ];then
        exit
      fi
      sleeps=$(expr $sleeps - 1)
      sleep 10
    done
    sleep $remainder
  else
    sleep $1
  fi
}

function hpgetbatch {
  $HP_CURL -o "$HP_WD$HP_CMDFILE"\
    "$HP_SERVER/httpov.php?command=getbatch&job=$job&$HP_STDARGS" &>/dev/null
}

function hpabortbatch {
  $HP_CURL -o "$HP_WD$HP_CMDFILE"\
    "$HP_SERVER/httpov.php?command=abortbatch&job=$job&batch=$batch&$HP_STDARGS" >/dev/null
}

function hpgetdata {
  $HP_CURL -o "$name.zip" "$HP_SERVER/jobs/$name.zip" &>/dev/null
}

function hppanic {
  echo $(date)': Server communication failed!'
  echo
  curl -o "$HP_WD$HP_CMDFILE"\
    "$HP_SERVER/httpov.php?command=hello&$HP_STDARGS"
  exit 1
}

function hptry {
  trytime=1
  trytimes=$HP_TRYTIMES
  trymessage=1
  if ( [ $trytimes = 0 ] );then
    while :; do
      if ( $1 );then
        return
      else
        if ( [ $trymessage != 0 ] );then
          echo "Network trouble."
          trymessage=0
        fi
        echo "Retrying until successful"
        hpsleep $trytime
        trytime=$(hpupsleep $trytime)
      fi
    done
  else
    while ( [ $trytimes != 0 ] );do
      trytimes=$( expr $trytimes - 1 )
      if ( $1 );then
        return
      else
        if ( [ $trymessage != 0 ] );then
          echo "Network trouble."
          trymessage=0
        fi
        echo "Retrying: $trytimes"
        hpsleep $trytime
        trytime=$(hpupsleep $trytime)
      fi
    done
  fi
  hppanic
}

function hpactiveloop {
  while :; do
    sleep 60
    $HP_CURL -o "$HP_WD$HP_CMDFILE"\
      "$HP_SERVER/httpov.php?command=active&job=$job&batch=$batch&$HP_STDARGS" &>/dev/null
  done
}

function hpactiveloop_run {
  hpactiveloop $HP_ACTIVELOOP &
  HP_ACTIVELOOP=$!
}

function hpactiveloop_kill {
  if [ $HP_ACTIVELOOP -gt 0 ];then
    kill $HP_ACTIVELOOP
  fi
  HP_ACTIVELOOP=0
}

# Main loop starts here

lastcheck=0
echo
echo "$(date): HTTPov client $HP_VERSION starting."
hp_sleep=0
hpcheckver

while ( [ "$HP_PASSWORD" != "changeme" ] )
do
  jobmessage=1
  hp_sleep=1

  # Job fetch loop

  while [ $hp_sleep = 1 ]
  do
    hptry hpgetjob
    if [ $? -gt 0 ];then
      hppanic
    fi
    i=0

    hpreadcommands

    if [ -a $HP_WD""$HP_ABORTFILE ];then
      exit
    fi
  done

  # Get and decompress job

  sleeptime=$sleepseed
  echo "$(date): Fetching data for job $job ($name)"

  hptry hpgetdata

  echo "Decompressing data for job $job ($name)"
  nice -n "$nicelevel" unzip -o "$name.zip" &>/dev/null
  previous=$(pwd)
  if ! cd "$name" &>/dev/null;then
    echo "Could not find the decompressed job."
    echo "Is the directory name the same as the archive name?"
    exit 1
  fi

  # Batch fetch loop

  while ( [ $job != 0 ] )
  do

    echo "$(date): Fetching batch for job $job ($name)"
    hptry hpgetbatch

    hpreadcommands

    if [ $render = 1 ];then
      echo "Starting render job:"
      echo "Batch:      $batch"
      if [ "$slice" = "" ];then
        echo "Startframe: $startframe"
        echo "Stopframe:  $stopframe"
      else
        echo "Frame: $startframe"
        echo "Slice: $slice"
      fi
      trap 'hpabort' TERM INT
      hpactiveloop_run
      if [ "$slice" = "" ];then
        nice -n "$nicelevel" "$HP_POV" -D pov.ini +O"$name"_ \
          "+SF$startframe" "+EF$stopframe" &>batchreport.txt \
          || povstatus="failed"
      else
        nice -n "$nicelevel" "$HP_POV" -D pov.ini +O"$name"_ \
          "+SF$startframe" "+EF$stopframe" "+SR$startrow" "+ER$endrow" +FP \
          &>batchreport.txt || povstatus="failed"
      fi
      hpactiveloop_kill
      trap 'hpabort' TERM INT
      grep "Aborting render" batchreport.txt &>/dev/null&&povstatus="failed"
      grep "Parse Error" batchreport.txt &>/dev/null&&povstatus="failed"
      framereport=""
      places=${#frames}
      if [ "$slice" = "" ];then
        for frame in $(seq $startframe $stopframe);do
          frame=$(printf %0"$places"d "$frame")
          if [ -a "$name"_"$frame.png" ];then
            framereport="$framereport$name"_"$frame.png created."
          else
            framereport="$framereport$name"_"$frame.png is missing!\n"
            povstatus="failed";
          fi
        done
      else
        fullstartframe=$(printf %0"$places"d $startframe)
        if [ -a $name"_"$fullstartframe".ppm" ];then
          fullslice=$(printf "%04d" "$slice")
          framereport="$framereport$name"_"$fullstartframe"_"$fullslice.ppm created."
        else 
          framereport="$framereport$name"_"$fullstartframe.ppm is missing!\n"
          povstatus="failed";
        fi
      fi

      if [ "$povstatus" = "failed" ];then
        hptry hpabortbatch
        cat batchreport.txt
        echo
        if [ "$framereport" != "" ];then
          echo -e "$framereport"
          echo -e "$framereport" >>batchreport.txt
        fi
        echo "$(date): Povray failed, client aborting."
        exit 1
      else
        povstatus=""
        if [ "$framereport" != "" ];then
          echo -e "$framereport"
        fi
        fullstart=$(printf '%08d' "$startframe")
        mkdir "$name"_frame_$fullstart
        for frame in $(seq "$startframe" "$stopframe");do
          frame=$(printf %0"$places"d "$frame")
          if [ "$slice" = "" ];then
            mv "$name"_"$frame.png" \
              "$name"_frame_$fullstart
          else
            fullslice=$(printf "%04d" "$slice")
            mv "$name"_"$frame.ppm" \
              "$name"_frame_"$fullstart"/slice_"$fullslice.ppm"
            mv batchreport.txt \
              "$name"_frame_"$fullstart"/batchreport_"$fullslice.txt"
          fi
        done

        echo "$(date): Compressing data for job $job ($name)"
        if [ "$slice" = "" ];then
          nice -n "$nicelevel" zip -r "$name"_frame_"$fullstart" \
            "$name"_frame_"$fullstart" &>/dev/null
          echo "$(date): Uploading batch data"
          hptry hppostbatch
          rm -rf "$name"_frame_"$fullstart.zip" "$name"_frame_"$fullstart"
        else
          nice -n "$nicelevel" zip -r \
            "$name"_frame_"$fullstart"_"$fullslice.zip"\
            "$name"_frame_"$fullstart" &>/dev/null
          echo "$(date): Uploading batch data"
          hptry hppostbatch
          rm -rf "$name"_frame_"$fullstart"_"$fullslice.zip"\
            "$name"_frame_"$fullstart"
        fi
        echo
      fi
    else
      echo "$(date): No batch received."
      job=0
    fi

    if [ -a $HP_WD""$HP_ABORTFILE ];then
      job=0
    fi
  done
  echo "$(date): Deleting job data"
  cd "$previous"
  rm -rf "$name" "$name.zip" "$HP_CMDFILE"
  if [ -a "$HP_ABORTFILE" ];then
    cd "$HP_PWD"
    exit
  fi
  sleeptime=$sleepseed
done
if [ "$HP_PASSWORD" = "changeme" ];then
  echo "Change the password."
fi
