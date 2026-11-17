<#
.SYNOPSIS
    Instala todas as dependencias do Mini Sensor Dashboard em um PC Windows.

.DESCRIPTION
    1. Python 3.12 (instala se nao houver Python >= 3.12)
    2. Ambiente virtual .venv com PyQt6, PyQtGraph, PySerial e NumPy
    3. Arduino IDE 2, core "Arduino AVR Boards" e bibliotecas OneWire e
       DallasTemperature
    4. Verificacao: importacao dos pacotes, testes automaticos e compilacao
       do firmware para Uno e Leonardo

    Se a pasta "dependencias" (gerada por preparar_pacote_offline.bat) existir,
    os arquivos dela sao usados e a internet nao e necessaria. Caso contrario,
    tudo e baixado dos sites oficiais.

    Nao exige administrador: Python e Arduino IDE sao instalados para o
    usuario atual.

.PARAMETER SemArduino
    Nao instala Arduino IDE, core nem bibliotecas (use em um PC que so vai
    rodar o dashboard, com o Arduino ja gravado).

.PARAMETER SemVerificacao
    Pula os testes automaticos e a compilacao de verificacao do firmware.
#>
param(
    [switch]$SemArduino,
    [switch]$SemVerificacao
)

$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot 'config_instalacao.ps1')
Initialize-Network

$logDir = Join-Path $ProjectRoot 'logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$logFile = Join-Path $logDir ("instalacao_{0:yyyyMMdd_HHmmss}.log" -f (Get-Date))
try { Start-Transcript -Path $logFile | Out-Null } catch { }

$offline = Test-Path $DepsDir
$problems = New-Object System.Collections.Generic.List[string]

Write-Host ''
Write-Host '=================================================================' -ForegroundColor Cyan
Write-Host '  MINI SENSOR DASHBOARD - instalacao de dependencias' -ForegroundColor Cyan
Write-Host '=================================================================' -ForegroundColor Cyan
Write-Info "Projeto : $ProjectRoot"
if ($offline) {
    Write-Info "Modo    : OFFLINE (usando a pasta 'dependencias')"
} else {
    Write-Info 'Modo    : ONLINE (download dos sites oficiais)'
}

# Executa o arduino-cli mostrando a saida, mas omitindo os avisos sobre o
# indice de bibliotecas (library_index), que nao e necessario e sempre falha
# sem internet. O sucesso e avaliado pelo codigo de saida.
function Invoke-ArduinoCli([string[]]$CliArgs) {
    & $script:cli @CliArgs 2>&1 | ForEach-Object { "$_" } |
        Where-Object { $_ -and $_ -notmatch 'library_index' -and $_ -notmatch 'Error initializing instance' } |
        ForEach-Object { Write-Info $_ }
    return $LASTEXITCODE
}

function Stop-Install([string]$Message) {
    Write-Fail $Message
    Write-Host ''
    Write-Host "Log completo: $logFile"
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}

# ============================================================================
# 1. Python
# ============================================================================
Write-Step "1/4  Python $PythonMinimum+"

$exactTag = ''
if ($offline -and (Test-Path $WheelsDir)) { $exactTag = $PythonOfflineTag }
$python = Find-Python -Exact $exactTag

if ($python) {
    Write-Ok "Python $(Get-PythonVersion $python) encontrado: $python"
} else {
    $installer = Join-Path $DepsDir $PythonInstallerName
    if (-not (Test-Path $installer)) {
        if ($offline) { Write-Warn "Instalador do Python ausente no pacote offline; tentando baixar." }
        $installer = Join-Path $env:TEMP $PythonInstallerName
        try { Invoke-Download $PythonInstallerUrl $installer }
        catch { Stop-Install "Falha ao baixar o Python: $($_.Exception.Message)" }
    }
    Write-Info "Instalando Python $PythonVersion para o usuario atual (1-3 minutos)..."
    $pyArgs = @('/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1',
                'InstallLauncherAllUsers=0', 'Include_test=0', 'Include_doc=0', 'SimpleInstall=1')
    $proc = Start-Process -FilePath $installer -ArgumentList $pyArgs -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        Stop-Install "O instalador do Python terminou com codigo $($proc.ExitCode)."
    }
    $python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    if (-not (Test-Path $python)) { $python = Find-Python -Exact $PythonOfflineTag }
    if (-not $python) { Stop-Install 'Python instalado, mas o executavel nao foi encontrado.' }
    Write-Ok "Python $(Get-PythonVersion $python) instalado: $python"
}

# ============================================================================
# 2. Pacotes Python (.venv)
# ============================================================================
Write-Step '2/4  Pacotes Python (PyQt6, PyQtGraph, PySerial, NumPy)'

$baseVersion = Get-PythonVersion $python
$recreate = $true
if (Test-Path $VenvPython) {
    $venvVersion = Get-PythonVersion $VenvPython
    if ($venvVersion -and $venvVersion.Major -eq $baseVersion.Major -and $venvVersion.Minor -eq $baseVersion.Minor) {
        & $VenvPython -c "import pip" 2>$null
        if ($LASTEXITCODE -eq 0) { $recreate = $false }
    }
}
if ($recreate) {
    if (Test-Path $VenvDir) {
        Write-Info 'Ambiente .venv existente esta incompativel ou corrompido; recriando.'
        Remove-Item -Recurse -Force $VenvDir
    }
    Write-Info 'Criando ambiente virtual .venv ...'
    & $python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) { Stop-Install 'Falha ao criar o ambiente virtual.' }
}
Write-Ok "Ambiente virtual: $VenvDir"

if ($offline -and (Test-Path $WheelsDir)) {
    Write-Info 'Instalando a partir de dependencias\wheels (sem internet)...'
    & $VenvPython -m pip install --disable-pip-version-check --no-index --find-links $WheelsDir -r $Requirements
} else {
    Write-Info 'Baixando e instalando pacotes (cerca de 110 MB na primeira vez)...'
    & $VenvPython -m pip install --disable-pip-version-check --upgrade pip | Out-Null
    & $VenvPython -m pip install --disable-pip-version-check -r $Requirements
}
if ($LASTEXITCODE -ne 0) {
    Stop-Install 'Falha ao instalar os pacotes Python. Verifique a internet (ou o pacote offline) e rode novamente. Se o projeto estiver no OneDrive, pause a sincronizacao durante a instalacao.'
}
# Mesmo marcador usado pelo run.bat: evita reinstalar na primeira execucao.
Copy-Item -Force $Requirements (Join-Path $VenvDir 'requirements.installed')

$check = & $VenvPython -c "import PyQt6.QtWidgets, pyqtgraph, serial, numpy; print('ok')" 2>&1
if ("$check" -match 'ok$') {
    Write-Ok 'Pacotes instalados e carregando corretamente.'
} else {
    Write-Fail "Os pacotes foram instalados, mas nao carregam: $check"
    if ("$check" -match 'Controle de Aplicativo|Application Control') {
        Write-Info 'O Smart App Control do Windows bloqueou uma DLL. Nao altere as versoes do requirements.txt.'
    }
    Stop-Install 'Corrija o problema acima e execute o instalador novamente.'
}

# ============================================================================
# 3. Arduino IDE, core AVR e bibliotecas
# ============================================================================
$cli = $null
if ($SemArduino) {
    Write-Step '3/4  Arduino (ignorado: -SemArduino)'
} else {
    Write-Step '3/4  Arduino IDE, core AVR e bibliotecas'

    if (Find-ArduinoIde) {
        Write-Ok "Arduino IDE ja instalada: $(Find-ArduinoIde)"
    } else {
        $ideInstaller = Join-Path $ArduinoDepsDir $ArduinoIdeInstallerName
        if (-not (Test-Path $ideInstaller)) {
            $ideInstaller = Join-Path $env:TEMP $ArduinoIdeInstallerName
            try { Invoke-Download $ArduinoIdeInstallerUrl $ideInstaller }
            catch { $problems.Add("Arduino IDE nao baixada: $($_.Exception.Message)"); $ideInstaller = $null }
        }
        if ($ideInstaller) {
            Write-Info "Instalando Arduino IDE $ArduinoIdeVersion para o usuario atual (1-2 minutos)..."
            $proc = Start-Process -FilePath $ideInstaller -ArgumentList @('/S', '/currentuser') -Wait -PassThru
            if ($proc.ExitCode -eq 0 -and (Find-ArduinoIde)) {
                Write-Ok "Arduino IDE instalada: $(Find-ArduinoIde)"
            } else {
                $problems.Add("Instalador da Arduino IDE terminou com codigo $($proc.ExitCode).")
            }
        }
    }

    $cli = Find-ArduinoCli
    if (-not $cli) {
        $problems.Add('arduino-cli nao encontrado: instale a Arduino IDE manualmente e rode o instalador de novo.')
    } else {
        Write-Info "arduino-cli: $cli"
        $dataDir = (& $cli config get directories.data | Select-Object -First 1).Trim()
        $userDir = (& $cli config get directories.user | Select-Object -First 1).Trim()

        # --- Core AVR ---
        $stagingSrc = Join-Path $ArduinoDepsDir 'staging\packages'
        if ($offline -and (Test-Path $stagingSrc)) {
            # Copia o cache e o indice: o arduino-cli instala a partir dele sem baixar.
            $stagingDst = Join-Path $dataDir 'staging\packages'
            New-Item -ItemType Directory -Force $stagingDst | Out-Null
            Copy-Item -Force (Join-Path $stagingSrc '*') $stagingDst
            foreach ($f in @('package_index.json', 'package_index.json.sig')) {
                $src = Join-Path $ArduinoDepsDir $f
                if ((Test-Path $src) -and -not (Test-Path (Join-Path $dataDir $f))) { Copy-Item $src $dataDir }
            }
        } else {
            Write-Info 'Atualizando indice de placas...'
            $null = Invoke-ArduinoCli @('core', 'update-index')
        }
        Write-Info "Instalando core $ArduinoCore ..."
        $rc = Invoke-ArduinoCli @('core', 'install', $ArduinoCore)
        if ($rc -eq 0) { Write-Ok "Core $ArduinoCore instalado." }
        else { $problems.Add("Core $ArduinoCore nao instalado (sem internet?). Abra a Arduino IDE conectado a internet: ela instala 'Arduino AVR Boards' automaticamente.") }

        # --- Bibliotecas ---
        $libZipDir = Join-Path $ArduinoDepsDir 'libraries'
        if ($offline -and (Test-Path $libZipDir)) {
            $libDst = Join-Path $userDir 'libraries'
            New-Item -ItemType Directory -Force $libDst | Out-Null
            foreach ($spec in $ArduinoLibraries) {
                $name, $ver = $spec.Split('@')
                $zip = Join-Path $libZipDir "$name-$ver.zip"
                if (-not (Test-Path $zip)) { $problems.Add("Biblioteca $spec ausente no pacote offline."); continue }
                $tmp = Join-Path $env:TEMP "mini-dashboard-lib-$name"
                if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
                Expand-Archive -Path $zip -DestinationPath $tmp -Force
                $inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
                $target = Join-Path $libDst $name
                if (Test-Path $target) { Remove-Item -Recurse -Force $target }
                Move-Item $inner.FullName $target
                Remove-Item -Recurse -Force $tmp
                Write-Ok "Biblioteca $spec copiada para $target"
            }
        } else {
            Write-Info "Instalando bibliotecas $($ArduinoLibraries -join ', ') ..."
            $null = Invoke-ArduinoCli @('lib', 'update-index')
            $rc = Invoke-ArduinoCli (@('lib', 'install') + $ArduinoLibraries)
            if ($rc -eq 0) { Write-Ok 'Bibliotecas instaladas.' }
            else { $problems.Add('Bibliotecas Arduino nao instaladas. Instale OneWire e DallasTemperature pelo Gerenciador de Bibliotecas da IDE.') }
        }
    }
}

# ============================================================================
# 4. Verificacao
# ============================================================================
if ($SemVerificacao) {
    Write-Step '4/4  Verificacao (ignorada: -SemVerificacao)'
} else {
    Write-Step '4/4  Verificacao'
    Push-Location $ProjectRoot
    & $VenvPython -m unittest discover -s tests 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Info "$_" }
    $testsOk = ($LASTEXITCODE -eq 0)
    Pop-Location
    if ($testsOk) { Write-Ok 'Testes automaticos do dashboard aprovados.' }
    else { $problems.Add('Testes automaticos falharam (veja o log).') }

    if ($cli) {
        foreach ($board in @('uno', 'leonardo')) {
            $buildDir = Join-Path $env:TEMP "mini-dashboard-build-$board"
            & $cli compile --fqbn "arduino:avr:$board" --build-path $buildDir $SketchDir 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { Write-Ok "Firmware compila para Arduino $board." }
            else { $problems.Add("Firmware nao compilou para Arduino $board (core ou bibliotecas ausentes).") }
        }
    }
}

# ============================================================================
# Resumo
# ============================================================================
Write-Host ''
Write-Host '=================================================================' -ForegroundColor Cyan
if ($problems.Count -eq 0) {
    Write-Host '  INSTALACAO CONCLUIDA SEM PENDENCIAS' -ForegroundColor Green
} else {
    Write-Host '  INSTALACAO CONCLUIDA COM PENDENCIAS:' -ForegroundColor Yellow
    foreach ($p in $problems) { Write-Warn $p }
}
Write-Host '=================================================================' -ForegroundColor Cyan
Write-Host ''
Write-Host 'Proximos passos:'
Write-Host '  1. Monte o circuito (docs\GUIA_MONTAGEM.md) e conecte o Arduino.'
Write-Host '  2. Clones com chip CH340 podem exigir o driver do fabricante (WCH).'
Write-Host '  3. Grave o firmware arduino\sensor_monitor\sensor_monitor.ino pela Arduino IDE.'
Write-Host '  4. Execute run.bat, escolha a porta COM e clique em Conectar.'
Write-Host ''
Write-Host "Log desta instalacao: $logFile"
try { Stop-Transcript | Out-Null } catch { }
if ($problems.Count -gt 0) { exit 2 }
exit 0
