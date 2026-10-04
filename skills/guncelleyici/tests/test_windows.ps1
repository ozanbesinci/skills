#requires -Version 5.1
# Offline syntax + orchestration fixture tests. Never install real applications.
param()
$ErrorActionPreference='Stop'
$skill=Split-Path $PSScriptRoot -Parent
$results=New-Object System.Collections.Generic.List[object]
function Check([bool]$Condition,[string]$Name){
    if(-not $Condition){throw "FAIL: $Name"}
    $results.Add([pscustomobject]@{name=$Name;status='PASS'})
}
foreach($file in Get-ChildItem -LiteralPath $skill -Recurse -File -Filter '*.ps1'){
    $tokens=$null;$errors=$null
    $null=[Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$tokens,[ref]$errors)
    if($errors.Count){throw ($file.Name+': '+($errors|Out-String))}
    Check $true ('syntax:'+ $file.Name)
}
$testRoot=Join-Path $env:TEMP ('guncelleyici-offline-test-'+[guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($testRoot)
$oldLocal=$env:LOCALAPPDATA;$oldProfile=$env:USERPROFILE;$oldTemp=$env:TEMP
try{
    $env:TEMP=$testRoot
    $env:LOCALAPPDATA=Join-Path $testRoot 'local';$env:USERPROFILE=Join-Path $testRoot 'profile'
    . (Join-Path $skill 'scripts\core.ps1')
    $script:StateRoot=Join-Path $testRoot 'state'
    $script:Versions=@{python='1.0.0';node='1.0.0';pnpm='1.0.0';duckdb='1.0.0';powerbi='1.0.0';offer='1.0.0';libraries='1.0.0';pdf='1.0.0'}
    $script:InstallCalls=0
    function Get-Observation([string]$Key,[switch]$LocalOnly,[string]$Cache,[bool]$Repair=$false){
        return [pscustomobject]@{local=[ordered]@{version=$script:Versions[$Key];path=('fixture/'+$Key)};surum=$script:Versions[$Key];target=$(if($LocalOnly){$null}else{[pscustomobject]@{version='2.0.0';repair=$Repair}});blocked=$false;matched=0;health='NOT_RUN'}
    }
    function Discover-Runtimes {$script:Python='fixture-python';$script:Node='fixture-node'}
    function Invoke-Selected([string]$Key,$Component,[string]$SessionPath){
        $script:InstallCalls++;$script:Versions[$Key]=$Component.target.version
        return [pscustomobject]@{key=$Key;ozet='GEÇTİ';surum=$Component.target.version;health='PASS'}
    }
    function Remove-LegacySkill {return @([pscustomobject]@{action='fixture-no-mutation'})}
    function Assert-MaintenanceWindow {if($env:GUNCELLEYICI_MAINTENANCE -ne 'confirmed'){throw 'Fixture maintenance guard.'}}
    $scan=Build-Plan $false @()
    Check ($scan.rows.Count -eq 8) 'Eight rows including optional PDF'
    Check ($scan.status -eq 'selection_required') 'Update candidates returned'
    Check ($script:InstallCalls -eq 0) 'Scan never invokes install'
    Check (-not (Test-Path -LiteralPath $script:StateRoot)) 'Scan does not persist installation state'
    Check (-not @($scan.rows|Where-Object {$_.key -eq 'pdf'})[0].secili) 'PDF is opt-in'
    $rejected=$false
    try{$null=Apply-Plan $scan.plan_file ('0'*64) @('node') $true $true}catch{$rejected=$true}
    Check $rejected 'Changed plan rejected'
    Check ($script:InstallCalls -eq 0) 'Changed plan has no install calls'
    $rejected=$false
    try{$null=Apply-Plan $scan.plan_file $scan.fingerprint @('bad') $true $true}catch{$rejected=$true}
    Check $rejected 'Unknown selection rejected'
    $rejected=$false
    try{$null=Apply-Plan $scan.plan_file $scan.fingerprint @('node') $true $false}catch{$rejected=$true}
    Check $rejected 'Apply without explicit confirmation rejected'
    Check ($script:InstallCalls -eq 0) 'Unconfirmed apply has no install calls'
    $cancel=Apply-Plan $scan.plan_file $scan.fingerprint @() $true $false
    Check ($cancel.status -eq 'cancelled') 'Empty selection cancels'
    $script:Versions.node='1.0.1'
    $stale=Apply-Plan $scan.plan_file $scan.fingerprint @('node') $true $true
    Check ($stale.status -eq 'stale') 'Local change detected under lock'
    Check ($script:InstallCalls -eq 0) 'Stale local state not installed'
    $script:Versions.node='1.0.0'
    $done=Apply-Plan $scan.plan_file $scan.fingerprint @('node') $true $true
    Check ($done.status -eq 'completed') 'Approved fixture installation completes'
    Check ($script:InstallCalls -eq 1) 'Only selected component invoked'
    Check ($done.maintenance.Count -eq 1) 'Maintenance result retained'
    Check ((Get-Content -LiteralPath $done.report -Raw|ConvertFrom-Json).rows.Count -eq 8) 'Audit result contains final rows'
    Check (-not (Test-Path -LiteralPath (Join-Path $script:StateRoot 'active-transaction.json'))) 'Completed transaction journal cleared'
    $guard=Enter-Guard
    try{
        $blocked=$false;try{$second=Enter-Guard;$second.Dispose()}catch{$blocked=$true}
        Check $blocked 'Shared update guard rejects second writer'
    }finally{$guard.Dispose()}
    $sample=[pscustomobject]@{tools=@([pscustomobject]@{name='single'})}
    $value=Read-Field $sample 'tools'
    Check ($value -is [array] -and $value.Count -eq 1) 'Single-item arrays preserved by field reader'
    $summary=[ordered]@{suite='Windows PowerShell 5.1 offline syntax/orchestration';status='PASS';assertions=$results.Count;results=$results.ToArray();live_installations='NOT_RUN';excel_com='NOT_RUN';authenticode_chain='NOT_RUN';pdf_native_extension='NOT_RUN'}
    '@@TEST '+($summary|ConvertTo-Json -Depth 8 -Compress)
}finally{
    $env:LOCALAPPDATA=$oldLocal;$env:USERPROFILE=$oldProfile;$env:TEMP=$oldTemp
    if(Test-Path -LiteralPath $testRoot){Remove-Item -LiteralPath $testRoot -Recurse -Force}
}
