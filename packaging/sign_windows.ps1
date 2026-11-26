# Signs Rakez Windows binaries with the "Mostafa Elwakil" code-signing certificate.
#
# Usage (local):
#   powershell -ExecutionPolicy Bypass -File packaging\sign_windows.ps1 -Path dist\Rakez.exe
#   powershell -ExecutionPolicy Bypass -File packaging\sign_windows.ps1 -Path dist\Rakez-Setup-2.2.0.exe
#
# The certificate is looked up in Cert:\CurrentUser\My (subject CN=Mostafa Elwakil,
# Code Signing EKU, private key present). In CI the workflow imports a PFX first,
# or you can point at one explicitly:
#   -PfxPath C:\path\rakez-codesign.pfx -PfxPassword <password>
#
# Requires no Windows SDK: Set-AuthenticodeSignature ships with Windows PowerShell.
# Timestamping keeps existing signatures valid after the certificate expires.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)]
    [string[]] $Path,

    [string] $Subject = "CN=Mostafa Elwakil",

    [string] $PfxPath = $env:SIGNING_PFX_PATH,

    [string] $PfxPassword = $env:SIGNING_PFX_PASSWORD,

    [string] $TimestampServer = "http://timestamp.digicert.com",

    # A self-signed certificate is not trusted on machines that never installed
    # it, so "UnknownError" is expected there. Set -RequireTrusted to fail instead.
    [switch] $RequireTrusted
)

$ErrorActionPreference = "Stop"

function Get-CodeSigningCertificate {
    if ($PfxPath) {
        if (-not (Test-Path $PfxPath)) { throw "PFX not found: $PfxPath" }
        $secure = ConvertTo-SecureString -String $PfxPassword -AsPlainText -Force
        return [System.Security.Cryptography.X509Certificates.X509Certificate2]::new(
            (Resolve-Path $PfxPath).Path, $secure,
            [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet)
    }

    $cert = Get-ChildItem Cert:\CurrentUser\My |
        Where-Object {
            if ($_.Subject -notlike "$Subject*" -or -not $_.HasPrivateKey) { return $false }
            $eku = @($_.EnhancedKeyUsageList | ForEach-Object { $_.ObjectId })
            if ($eku -contains "1.3.6.1.5.5.7.3.3") { return $true }
            $raw = $_.Extensions |
                Where-Object { $_.Oid.Value -eq "2.5.29.37" } |
                ForEach-Object { $_.Format($false) }
            return ($raw -join ";") -match "1\.3\.6\.1\.5\.5\.7\.3\.3"
        } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1

    if (-not $cert) {
        throw "No code-signing certificate for '$Subject' in Cert:\CurrentUser\My. Import the PFX first or pass -PfxPath."
    }
    return $cert
}

$cert = Get-CodeSigningCertificate
Write-Host "Signing with: $($cert.Subject) (expires $($cert.NotAfter.ToString('yyyy-MM-dd')))"

$signed = 0
$failed = 0

foreach ($item in $Path) {
    $file = Get-Item -Path $item -ErrorAction SilentlyContinue
    if (-not $file) { Write-Error "File not found: $item"; $failed++; continue }

    Write-Host "  -> $($file.FullName)"
    $result = Set-AuthenticodeSignature -FilePath $file.FullName -Certificate $cert `
        -HashAlgorithm SHA256 -TimestampServer $TimestampServer

    $check = Get-AuthenticodeSignature -FilePath $file.FullName
    $trusted = $check.Status -eq "Valid"
    $acceptable = $trusted -or ((-not $RequireTrusted) -and $check.SignerCertificate -and $check.SignerCertificate.Subject -like "$Subject*")

    if ($acceptable) {
        $stamp = if ($check.TimeStamperCertificate) { "timestamped" } else { "NO TIMESTAMP" }
        Write-Host "     $($check.Status) ($stamp)"
        $signed++
    }
    else {
        Write-Error "Signature verification failed for $($file.Name): $($check.Status) - $($check.StatusMessage)"
        $failed++
    }
}

Write-Host "Signed: $signed  Failed: $failed"
if ($failed -gt 0) { exit 1 }
