# install.ps1
# Created by Joseph Yennaco (9/1/2016)

# Set the Error action preference when an exception is caught
$ErrorActionPreference = "Stop"

# Start a stopwatch to record asset run time
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

# Determine this script's parent directory
# For Powershell v2 use the following (default):
$scriptPath = split-path -parent $MyInvocation.MyCommand.Definition
# For Powershell > v3 you can use one of the following:
#     $scriptPath = Split-Path -LiteralPath $(if ($PSVersionTable.PSVersion.Major -ge 3) { $PSCommandPath } else { & { $MyInvocation.ScriptName } })
#     $scriptPath = $PSScriptRoot

# Load the PATH environment variable
$env:PATH = [Environment]::GetEnvironmentVariable("PATH", "Machine")

########################### VARIABLES ###############################

# Get the CONS3RT environment variables
$global:ASSET_DIR = $null
$global:DEPLOYMENT_HOME = $null
$global:DEPLOYMENT_PROPERTIES = $null

# exit code
$exitCode = 0

# Example file download URL
$fileDownloadUrl = "https://s3.amazonaws.com/jackpine-files/vs2017layout_enterprise.zip"

# Example file download destination
$fileDownloadDestination = "C:\vs2017layout_enterprise.zip"

# Configure the log file
$LOGTAG = "install-sample"
$TIMESTAMP = Get-Date -f yyyy-MM-dd-HHmmss
$LOGFILE = "C:\cons3rt\log\$LOGTAG-$TIMESTAMP.log"

######################### END VARIABLES #############################

######################## HELPER FUNCTIONS ############################

# Set up logging functions
function logger($level, $logstring) {
   $stamp = get-date -f yyyyMMdd-HHmmss
   $logmsg = "$stamp - $LOGTAG - [$level] - $logstring"
   write-output $logmsg
}
function logErr($logstring) { logger "ERROR" $logstring }
function logWarn($logstring) { logger "WARNING" $logstring }
function logInfo($logstring) { logger "INFO" $logstring }

function get_asset_dir() {
    if ($env:ASSET_DIR) {
        $global:ASSET_DIR = $env:ASSET_DIR
        return
    }
    else {
        logWarn "ASSET_DIR environment variable not set, attempting to determine..."
        if (!$PSScriptRoot) {
            logInfo "Determining script directory using the pre-Powershell v3 method..."
            $scriptDir = split-path -parent $MyInvocation.MyCommand.Definition
        }
        else {
            logInfo "Determining the script directory using the PSScriptRoot variable..."
            $scriptDir = $PSScriptRoot
        }
        if (!$scriptDir) {
            $msg =  "Unable to determine the script directory to get ASSET_DIR"
            logErr $msg
            throw $msg
        }
        else {
            $global:ASSET_DIR = "$scriptDir\.."
            logInfo "Determined ASSET_DIR to be: $global:ASSET_DIR"
        }
    }
}

function get_deployment_home() {
    # Ensure DEPLOYMENT_HOME is set
    if ($env:DEPLOYMENT_HOME) {
        $global:DEPLOYMENT_HOME = $env:DEPLOYMENT_HOME
        logInfo "Found DEPLOYMENT_HOME set to $global:DEPLOYMENT_HOME"
    }
    else {
        logWarn "DEPLOYMENT_HOME is not set, attempting to determine..."
        # CONS3RT Agent Run directory location
        $cons3rtAgentRunDir = "C:\cons3rt-agent\run"
        $deploymentDirName = get-childitem $cons3rtAgentRunDir -name -dir | select-string "Deployment"
        $deploymentDir = "$cons3rtAgentRunDir\$deploymentDirName"
        if (test-path $deploymentDir) {
            $global:DEPLOYMENT_HOME = $deploymentDir
        }
        else {
            $msg = "Unable to determine DEPLOYMENT_HOME from: $deploymentDir"
            logErr $msg
            throw $msg
        }
    }
    logInfo "Using DEPLOYMENT_HOME: $global:DEPLOYMENT_HOME"
}

function get_deployment_properties() {
    $deploymentPropertiesFile = "$global:DEPLOYMENT_HOME\deployment-properties.ps1"
    if ( !(test-path $deploymentPropertiesFile) ) {
        $msg = "Deployment properties not found: $deploymentPropertiesFile"
        logErr $msg
        throw $msg
    }
    else {
        $global:DEPLOYMENT_PROPERTIES = $deploymentPropertiesFile
        logInfo "Found deployment properties file: $global:DEPLOYMENT_PROPERTIES"
    }
    import-module $global:DEPLOYMENT_PROPERTIES -force -global
}

function reliable_download() {
    logInfo "Attempting to download file from URL: $fileDownloadUrl"

    # Attempt to download multiple times
    $numAttempts = 1
    $maxAttempts = 10
    $retryTime = 10
    while($true) {

        if($numAttempts -gt $maxAttempts) {
            $errMsg = "The number of attempts to download the file exceeded: $maxAttempts"
            logErr $errMsg
            throw $errMsg
        }

        logInfo "Attempting to download file, attempt #: $numAttempts of $maxAttempts"
        $downloadComplete = $false

        # Download the media file
        logInfo "Attempting to download file: $fileDownloadUrl to: $fileDownloadDestination"
        $start = get-date
        $Job = Start-BitsTransfer -Source $fileDownloadUrl -Destination $fileDownloadDestination -Asynchronous

        $checkTime = 10
        while (($Job.JobState -eq "Transferring") -or ($Job.JobState -eq "Connecting")) { 
            logInfo "Download in progress, job state is: $($Job.JobState), time taken is: $((get-date).subtract($start).ticks/10000000) seconds"
            sleep $checkTime
        }

        Switch($Job.JobState)
        {
            "Transferred" {
                logInfo "Download completed, time taken: $((get-date).subtract($start).ticks/10000000) seconds"
                Complete-BitsTransfer -BitsJob $Job
                $downloadComplete = $true
            }
            "Error" {
                $formattedError = $Job | Format-List
                logWarn "Download failed after $((get-date).subtract($start).ticks/10000000) seconds with error: $formattedError"
            } 
            default {
                logWarn "Unable to determine the failure status, will retry"
            }
        }

        if ($downloadComplete) {
            logInfo "Download complete, exiting the while loop..."
            break
        }

        $numAttempts++
        logInfo "Retrying in $retryTime seconds..."
        sleep $retryTime
    }
    logInfo "File download complete to: $fileDownloadDestination"
}

###################### END HELPER FUNCTIONS ##########################

######################## SCRIPT EXECUTION ############################

new-item $logfile -itemType file -force
start-transcript -append -path $logfile
logInfo "Running $LOGTAG..."

try {
    logInfo "Installing at: $TIMESTAMP"
    
    # Set asset dir
    logInfo "Setting ASSET_DIR..."
    get_asset_dir

    # Load the deployment properties as variables
    logInfo "Loading deployment properties..."
    get_deployment_home
    get_deployment_properties

	logInfo "ASSET_DIR: $global:ASSET_DIR"
	$mediaDir="$ASSET_DIR\media"

	# Exit if the media directory is not found
	if ( !(test-path $mediaDir) ) {
		$errMsg = "media directory not found: $mediaDir"
		logErr $errMsg
		throw $errMsg
	}
	else {
	    logInfo "Found the media directory: $mediaDir"
	}

	# Set an environment variable
	logInfo "Setting an environment variable ..."
	[Environment]::SetEnvironmentVariable("MY_VARIABLE", "C:\my_env_variable", "Machine")
		
	# Get an environment variable
	$PATH=[Environment]::GetEnvironmentVariable("PATH", "Machine")
	logInfo "PATH: $PATH"

    # Ensure your variable was loaded
    if ( !$cons3rt_user ) {
        $errMsg = "Required deployment property not found: cons3rt_user"
        logErr $errMsg
        throw $errMsg
    }
    else {
        logInfo "Found deployment property cons3rt_user: $cons3rt_user"
    }
}
catch {
    logErr "Caught exception after $($stopwatch.Elapsed): $_"
    $exitCode = 1
    $kill = (gwmi win32_process -Filter processid=$pid).parentprocessid
    if ( (Get-Process -Id $kill).ProcessName -eq "cmd" ) {
        logErr "Exiting using taskkill..."
        Stop-Transcript
        TASKKILL /PID $kill /T /F
    }
}
finally {
    logInfo "$LOGTAG complete in $($stopwatch.Elapsed)"
}

###################### END SCRIPT EXECUTION ##########################

logInfo "Exiting with code: $exitCode"
stop-transcript
get-content -Path $logfile
exit $exitCode
