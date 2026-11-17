# ============================================================================
#  Versoes e enderecos usados pelos scripts de instalacao.
#  Todas as versoes foram testadas juntas (Windows 11, Smart App Control ativo).
#  Altere somente depois de testar.
# ============================================================================

# --- Python -----------------------------------------------------------------
# numpy 2.5.5 exige Python >= 3.12. O pacote offline contem rodas (wheels)
# compiladas para CPython 3.12, por isso o modo offline exige exatamente 3.12.
$PythonVersion     = '3.12.10'
$PythonMinimum     = [version]'3.12'
$PythonOfflineTag  = '3.12'
$PythonInstallerName = "python-$PythonVersion-amd64.exe"
$PythonInstallerUrl  = "https://www.python.org/ftp/python/$PythonVersion/$PythonInstallerName"

# --- Arduino ------------------------------------------------------------------
$ArduinoIdeVersion       = '2.3.6'
$ArduinoIdeInstallerName = "arduino-ide_$($ArduinoIdeVersion)_Windows_64bit.exe"
$ArduinoIdeInstallerUrl  = "https://downloads.arduino.cc/arduino-ide/$ArduinoIdeInstallerName"
$ArduinoCore      = 'arduino:avr@1.8.8'
$ArduinoLibraries = @('OneWire@2.3.8', 'DallasTemperature@4.0.6')
# Arquivos do cache (staging) do Arduino CLI necessarios para instalar o core
# AVR sem internet: o proprio core, o compilador, o gravador e as ferramentas
# de descoberta de portas.
$ArduinoStagingPatterns = @(
    'avr-1.8.8.tar.bz2',
    'avr-gcc-7.3.0-atmel3.6.1-arduino7-*',
    'avrdude*',
    'arduinoOTA-*',
    'ctags-*',
    'serial-discovery*',
    'mdns-discovery*',
    'dfu-discovery*',
    'serial-monitor*'
)

# --- Caminhos do projeto ------------------------------------------------------
$ProjectRoot   = Split-Path -Parent $PSScriptRoot
$DepsDir       = Join-Path $ProjectRoot 'dependencias'
$WheelsDir     = Join-Path $DepsDir 'wheels'
$ArduinoDepsDir = Join-Path $DepsDir 'arduino'
$VenvDir       = Join-Path $ProjectRoot '.venv'
$VenvPython    = Join-Path $VenvDir 'Scripts\python.exe'
$Requirements  = Join-Path $ProjectRoot 'requirements.txt'
$SketchDir     = Join-Path $ProjectRoot 'arduino\sensor_monitor'

# --- Funcoes comuns -------------------------------------------------------------
function Write-Step([string]$Text)  { Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text)    { Write-Host "    [OK] $Text" -ForegroundColor Green }
function Write-Info([string]$Text)  { Write-Host "    $Text" }
function Write-Warn([string]$Text)  { Write-Host "    [AVISO] $Text" -ForegroundColor Yellow }
function Write-Fail([string]$Text)  { Write-Host "    [ERRO] $Text" -ForegroundColor Red }

function Initialize-Network {
    # PowerShell 5.1 usa TLS antigo por padrao; a barra de progresso deixa
    # Invoke-WebRequest muito lento.
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $global:ProgressPreference = 'SilentlyContinue'
}

function Invoke-Download([string]$Url, [string]$Destination) {
    Write-Info "Baixando $Url"
    $tmp = "$Destination.part"
    Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing
    Move-Item -Force $tmp $Destination
    $mb = [math]::Round((Get-Item $Destination).Length / 1MB, 1)
    Write-Ok "Salvo em $Destination ($mb MB)"
}

function Get-PythonVersion([string]$Exe) {
    try {
        $out = & $Exe -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return [version]($out | Select-Object -First 1) }
    } catch { }
    return $null
}

# Procura um Python utilizavel. Com -Exact '3.12' aceita somente essa versao.
function Find-Python([string]$Exact = '') {
    $candidates = New-Object System.Collections.Generic.List[string]
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($tag in @('-3.12', '-3.13', '-3.14', '-3')) {
            try {
                $exe = & $py.Source $tag -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $exe) { $candidates.Add(($exe | Select-Object -First 1).Trim()) }
            } catch { }
        }
    }
    foreach ($cmd in @(Get-Command python -All -ErrorAction SilentlyContinue)) {
        # O "python.exe" de WindowsApps e apenas um atalho para a Microsoft Store.
        if ($cmd.Source -notlike '*\WindowsApps\*') { $candidates.Add($cmd.Source) }
    }
    foreach ($ver in @('312', '313', '314')) {
        $candidates.Add((Join-Path $env:LOCALAPPDATA "Programs\Python\Python$ver\python.exe"))
        $candidates.Add((Join-Path $env:ProgramFiles "Python$ver\python.exe"))
    }
    foreach ($exe in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path $exe)) { continue }
        $v = Get-PythonVersion $exe
        if (-not $v) { continue }
        if ($Exact) {
            if ("$($v.Major).$($v.Minor)" -eq $Exact) { return $exe }
        } elseif ($v -ge $PythonMinimum) {
            return $exe
        }
    }
    return $null
}

# Localiza o arduino-cli: instalado no PATH ou embutido na Arduino IDE 2.
function Find-ArduinoCli {
    $cmd = Get-Command arduino-cli -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $embedded = 'resources\app\lib\backend\resources\arduino-cli.exe'
    foreach ($base in @((Join-Path $env:LOCALAPPDATA 'Programs\Arduino IDE'),
                        (Join-Path $env:ProgramFiles 'Arduino IDE'))) {
        $exe = Join-Path $base $embedded
        if (Test-Path $exe) { return $exe }
    }
    return $null
}

function Find-ArduinoIde {
    foreach ($exe in @((Join-Path $env:LOCALAPPDATA 'Programs\Arduino IDE\Arduino IDE.exe'),
                       (Join-Path $env:ProgramFiles 'Arduino IDE\Arduino IDE.exe'))) {
        if (Test-Path $exe) { return $exe }
    }
    return $null
}
