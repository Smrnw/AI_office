# Установка AI Office на Windows: Python, окружение, данные, ярлык и запуск.
# Обычно запускается двойным щелчком по install.bat в корне проекта.
#
#   -Yes           не задавать вопросов (поставить Python без подтверждения)
#   -NoLaunch      не запускать офис после установки
#   -NoShortcut    не создавать ярлыки
#   -ShortcutDir   куда положить ярлык (по умолчанию рабочий стол)
[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$NoLaunch,
    [switch]$NoShortcut,
    [string]$ShortcutDir = ''
)
$ErrorActionPreference = 'Stop'
# Вывод Python читаем в UTF-8: иначе кириллица в путях (например, в имени пользователя) превращается в «???»
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$DataDir = Join-Path $Root 'data'
$Venv = Join-Path $Root '.venv'
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
$AppName = 'AI Office'

function Say($t) { Write-Host "==> $t" -ForegroundColor Cyan }
function Ok($t) { Write-Host "  OK $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  !  $t" -ForegroundColor Yellow }
function Fail($t) { Write-Host "  X  $t" -ForegroundColor Red; exit 1 }
function Ask($q) {
    if ($Yes) { return $true }
    $a = Read-Host "$q [Y/n]"
    return ($a -eq '' -or $a -match '^[YyДд]')
}

# ---------------------------------------------------------------- Python

# Возвращает не путь, а способ запуска (команда + аргументы): путь из вывода Python на старых консолях
# мог прийти с испорченной кириллицей, а запуск той же командой, что прошла проверку, надёжен всегда
function Find-Python {
    $candidates = @(@('py', '-3.12'), @('py', '-3.13'), @('py', '-3.11'), @('py', '-3.10'), @('py', '-3'), @('python'), @('python3'))
    foreach ($p in @('Python313', 'Python312', 'Python311', 'Python310')) {
        $candidates += , @("$env:LOCALAPPDATA\Programs\Python\$p\python.exe")
    }
    foreach ($c in $candidates) {
        $exe = $c[0]
        $rest = @($c | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        try {
            $ver = & $exe @rest -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $ver -and ([version]"$ver".Trim()) -ge [version]'3.10') {
                return @{ Exe = $exe; Args = $rest; Name = ("$exe " + ($rest -join ' ')).Trim() + " (Python $ver)" }
            }
        } catch { }
    }
    return $null
}

Say 'Ищу Python 3.10+'
$SysPy = Find-Python
if (-not $SysPy) {
    if ((Get-Command winget -ErrorAction SilentlyContinue) -and (Ask 'Python не найден. Установить Python 3.12 через winget?')) {
        winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
        $SysPy = Find-Python
    }
    if (-not $SysPy) {
        Start-Process 'https://www.python.org/downloads/windows/'
        Fail 'Установите Python 3.10 или новее (галочка «Add python.exe to PATH») и запустите install.bat ещё раз.'
    }
}
Ok "Python: $($SysPy.Name)"

# ---------------------------------------------------------------- окружение

Say 'Готовлю виртуальное окружение .venv'
# окружение должно принадлежать этой папке: скопированное вместе с проектом .venv ссылается на старое место
$healthy = $false
if (Test-Path $VenvPy) {
    $prefix = & $VenvPy -c "import sys; print(sys.prefix)" 2>$null
    $norm = { param($x) [IO.Path]::GetFullPath("$x".Trim()).TrimEnd('\') }
    $healthy = ($LASTEXITCODE -eq 0) -and $prefix -and ((& $norm $prefix) -ieq (& $norm $Venv))
}
if (-not $healthy) {
    if (Test-Path $Venv) { Remove-Item -Recurse -Force $Venv }          # окружение от другой папки или сломано
    & $SysPy.Exe @($SysPy.Args) -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail 'Не удалось создать .venv' }
}
& $VenvPy -m pip install --disable-pip-version-check -q -r (Join-Path $Root 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Fail 'Не удалось установить зависимости (нужен интернет при первой установке)' }
Ok 'Зависимости установлены'

# ---------------------------------------------------------------- данные

Say "Папка данных: $DataDir"
New-Item -ItemType Directory -Force $DataDir | Out-Null

# ---------------------------------------------------------------- ярлыки

if (-not $NoShortcut) {
    Say 'Создаю ярлыки'
    $shell = New-Object -ComObject WScript.Shell
    $targets = @()
    if ($ShortcutDir) { $targets += $ShortcutDir } else {
        $targets += [Environment]::GetFolderPath('Desktop')
        $targets += [Environment]::GetFolderPath('Programs')
    }
    foreach ($dir in $targets) {
        New-Item -ItemType Directory -Force $dir | Out-Null
        $lnk = $shell.CreateShortcut((Join-Path $dir "$AppName.lnk"))
        $lnk.TargetPath = Join-Path $Root 'start.bat'
        $lnk.WorkingDirectory = $Root
        $lnk.IconLocation = (Join-Path $Root 'static\img\office.ico') + ',0'
        $lnk.WindowStyle = 7                                            # свёрнутое окно сервера
        $lnk.Description = 'AI Office: команда ИИ-агентов'
        $lnk.Save()
        Ok "Ярлык: $(Join-Path $dir "$AppName.lnk")"
    }
}

# ---------------------------------------------------------------- запуск

if (-not $NoLaunch) {
    Say 'Запускаю офис'
    Start-Process -FilePath (Join-Path $Root 'start.bat') -WorkingDirectory $Root -WindowStyle Minimized
    Ok 'Браузер откроется, как только сервер будет готов. Дальше запускайте ярлыком «AI Office».'
}
Write-Host ''
$Version = (& $VenvPy -c "import pixel_office; print(pixel_office.__version__)" 2>$null)
Write-Host "Готово. AI Office $Version" -ForegroundColor Green
