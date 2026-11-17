<#
.SYNOPSIS
    Baixa todas as dependencias para a pasta "dependencias", permitindo
    instalar o Mini Sensor Dashboard em um PC SEM internet.

.DESCRIPTION
    Execute em um PC COM internet que ja tenha Python 3.12+ e a Arduino IDE
    (por exemplo, o PC onde o projeto ja funciona). Conteudo gerado:

      dependencias\
        python-3.12.10-amd64.exe          instalador oficial do Python
        wheels\                            pacotes Python para CPython 3.12 / Windows 64 bits
        arduino\
          arduino-ide_2.3.6_Windows_64bit.exe   instalador da Arduino IDE (opcional)
          package_index.json(.sig)         indice de placas
          staging\packages\                core AVR 1.8.8 + compilador + gravador
          libraries\                       OneWire e DallasTemperature (.zip)

    Depois copie a pasta inteira do projeto para o outro PC e execute
    instalar_dependencias.bat: ele detecta a pasta "dependencias" e instala
    tudo sem internet.

.PARAMETER SemArduinoIDE
    Nao baixa o instalador da Arduino IDE (~150 MB). Use se o PC de destino
    ja tiver a IDE instalada.
#>
param(
    [switch]$SemArduinoIDE
)

$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot 'config_instalacao.ps1')
Initialize-Network

$problems = New-Object System.Collections.Generic.List[string]
Write-Host ''
Write-Host '=================================================================' -ForegroundColor Cyan
Write-Host '  MINI SENSOR DASHBOARD - preparacao do pacote offline' -ForegroundColor Cyan
Write-Host '=================================================================' -ForegroundColor Cyan
Write-Info "Destino: $DepsDir"
foreach ($d in @($DepsDir, $WheelsDir, $ArduinoDepsDir)) { New-Item -ItemType Directory -Force $d | Out-Null }

# ----------------------------------------------------------------------------
Write-Step "1/3  Instalador do Python $PythonVersion"
$pyInstaller = Join-Path $DepsDir $PythonInstallerName
if (Test-Path $pyInstaller) {
    Write-Ok "Ja existe: $pyInstaller"
} else {
    try { Invoke-Download $PythonInstallerUrl $pyInstaller }
    catch { $problems.Add("Python: $($_.Exception.Message)") }
}

# ----------------------------------------------------------------------------
Write-Step "2/3  Pacotes Python (wheels para CPython $PythonOfflineTag, Windows 64 bits)"
$py = $null
if (Test-Path $VenvPython) { $py = $VenvPython } else { $py = Find-Python }
if (-not $py) {
    $problems.Add('Nenhum Python 3.12+ neste PC para baixar os pacotes. Rode instalar_dependencias.bat aqui antes.')
} else {
    Write-Info "Usando $py"
    & $py -m pip download --disable-pip-version-check -r $Requirements -d $WheelsDir `
        --only-binary=:all: --platform win_amd64 --python-version $PythonOfflineTag --implementation cp
    if ($LASTEXITCODE -eq 0) {
        $count = (Get-ChildItem $WheelsDir -Filter *.whl).Count
        Write-Ok "$count pacotes em $WheelsDir"
    } else {
        $problems.Add('Falha ao baixar os pacotes Python (pip download).')
    }
}

# ----------------------------------------------------------------------------
Write-Step '3/3  Arduino: core AVR, bibliotecas e instalador da IDE'
$cli = Find-ArduinoCli
if (-not $cli) {
    $problems.Add('Arduino IDE/arduino-cli nao encontrado neste PC: a parte Arduino do pacote nao foi gerada.')
} else {
    Write-Info "arduino-cli: $cli"
    $dataDir = (& $cli config get directories.data | Select-Object -First 1).Trim()

    & $cli core update-index | Out-Null
    & $cli core download $ArduinoCore
    if ($LASTEXITCODE -ne 0) { $problems.Add("Falha ao baixar $ArduinoCore.") }
    & $cli lib update-index | Out-Null
    & $cli lib download @ArduinoLibraries
    if ($LASTEXITCODE -ne 0) { $problems.Add('Falha ao baixar as bibliotecas Arduino.') }

    # Core + ferramentas (cache do arduino-cli)
    $stagingSrc = Join-Path $dataDir 'staging\packages'
    $stagingDst = Join-Path $ArduinoDepsDir 'staging\packages'
    New-Item -ItemType Directory -Force $stagingDst | Out-Null
    $copied = 0
    foreach ($pattern in $ArduinoStagingPatterns) {
        foreach ($file in @(Get-ChildItem -Path $stagingSrc -Filter $pattern -File -ErrorAction SilentlyContinue)) {
            Copy-Item -Force $file.FullName $stagingDst
            $copied++
        }
    }
    foreach ($f in @('package_index.json', 'package_index.json.sig')) {
        $src = Join-Path $dataDir $f
        if (Test-Path $src) { Copy-Item -Force $src $ArduinoDepsDir }
    }
    if ($copied -ge 4) { Write-Ok "$copied arquivos do core/ferramentas copiados." }
    else { $problems.Add("Poucos arquivos do core encontrados no cache ($copied). Abra a Arduino IDE uma vez com internet e rode de novo.") }

    # Bibliotecas (.zip)
    $libDst = Join-Path $ArduinoDepsDir 'libraries'
    New-Item -ItemType Directory -Force $libDst | Out-Null
    foreach ($spec in $ArduinoLibraries) {
        $name, $ver = $spec.Split('@')
        $zip = Join-Path $dataDir "staging\libraries\$name-$ver.zip"
        if (Test-Path $zip) { Copy-Item -Force $zip $libDst; Write-Ok "Biblioteca $spec" }
        else { $problems.Add("Zip da biblioteca $spec nao encontrado em $zip.") }
    }

    # Instalador da IDE
    if ($SemArduinoIDE) {
        Write-Info 'Instalador da Arduino IDE ignorado (-SemArduinoIDE).'
    } else {
        $ideInstaller = Join-Path $ArduinoDepsDir $ArduinoIdeInstallerName
        if (Test-Path $ideInstaller) { Write-Ok "Ja existe: $ideInstaller" }
        else {
            try { Invoke-Download $ArduinoIdeInstallerUrl $ideInstaller }
            catch { $problems.Add("Arduino IDE: $($_.Exception.Message)") }
        }
    }
}

# ----------------------------------------------------------------------------
$sizeMb = [math]::Round(((Get-ChildItem $DepsDir -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 0)
Write-Host ''
Write-Host '=================================================================' -ForegroundColor Cyan
if ($problems.Count -eq 0) {
    Write-Host "  PACOTE OFFLINE PRONTO ($sizeMb MB)" -ForegroundColor Green
} else {
    Write-Host "  PACOTE OFFLINE GERADO COM PENDENCIAS ($sizeMb MB):" -ForegroundColor Yellow
    foreach ($p in $problems) { Write-Warn $p }
}
Write-Host '=================================================================' -ForegroundColor Cyan
Write-Host ''
Write-Host 'Para instalar em outro PC sem internet:'
Write-Host '  1. Copie a pasta inteira do projeto (incluindo "dependencias") para o outro PC.'
Write-Host '  2. Execute instalar_dependencias.bat.'
Write-Host ''
if ($problems.Count -gt 0) { exit 2 }
exit 0
