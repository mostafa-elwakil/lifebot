# Code signing (Windows)

Rakez binaries are Authenticode-signed as **Mostafa Elwakil**.

| Item | Value |
| --- | --- |
| Signer | `CN=Mostafa Elwakil, O=Mostafa Elwakil, C=EG` |
| Type | Self-signed code-signing certificate (RSA 3072, SHA-256, EKU 1.3.6.1.5.5.7.3.3) |
| Thumbprint | `0390E986EDA35A04880FA4D8CB64101CCE68AEB5` |
| Valid until | 2029-11-26 |
| Signed files | `dist/Rakez.exe` and `dist/Rakez-Setup-<version>.exe` |
| Timestamp | RFC 3161 (`http://timestamp.digicert.com`), so signatures outlive the certificate |

The certificate material lives **outside the repository** in `%USERPROFILE%\.rakez\signing\`
(`rakez-codesign.pfx`, `rakez-codesign.cer`, `pfx-password.txt`) and is never committed —
`*.pfx`, `*.p12`, `*.cer`, and `signing/` are in `.gitignore`. The public certificate is also
attached to every GitHub release as **`rakez-codesign.cer`** so users can trust it.

## Honest limitation

A self-signed certificate does **not** clear the SmartScreen warning for people who never
trusted it: Windows treats an unknown root as "Unknown publisher". It only gives the file a
verifiable signature and a publisher name once the certificate is trusted. To remove the
warning for everyone you need a paid OV/EV Code Signing certificate (or Microsoft Azure
Trusted Signing). The build pipeline does not care which certificate is used: replace the
PFX behind the same secrets and everything keeps working.

## Sign locally

```powershell
# The certificate must be in Cert:\CurrentUser\My (or pass -PfxPath/-PfxPassword).
powershell -ExecutionPolicy Bypass -File packaging\sign_windows.ps1 -Path dist\Rakez.exe
powershell -ExecutionPolicy Bypass -File packaging\sign_windows.ps1 `
    -Path dist\Rakez-Setup-2.2.0.exe -RequireTrusted:$false
```

Verify:

```powershell
Get-AuthenticodeSignature .\dist\Rakez-Setup-2.2.0.exe |
    Format-List Status, StatusMessage, @{n='Signer';e={$_.SignerCertificate.Subject}}
```

`Status` is `Valid` only where the self-signed root is trusted; on a fresh machine it is
`UnknownError` ("chain terminated in a root certificate which is not trusted").

## Trust the certificate on a machine

```powershell
certutil -f -user -addstore Root            .\rakez-codesign.cer
certutil -f -user -addstore TrustedPublisher .\rakez-codesign.cer
```

Then `Get-AuthenticodeSignature` reports `Valid` and UAC shows **Mostafa Elwakil** as the
program's publisher. Remove it later with `certutil -user -delstore Root <thumbprint>`.

Recreate the certificate (same subject, new key) and export it:

```powershell
$cert = New-SelfSignedCertificate -Type CodeSigningCert `
    -Subject "CN=Mostafa Elwakil, O=Mostafa Elwakil, C=EG" `
    -FriendlyName "Rakez Code Signing (Mostafa Elwakil)" `
    -KeyUsage DigitalSignature -KeyExportPolicy Exportable `
    -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 `
    -NotAfter (Get-Date).AddYears(3) -CertStoreLocation Cert:\CurrentUser\My `
    -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3")

$pwd = ConvertTo-SecureString "REPLACE-ME" -AsPlainText -Force
Export-PfxCertificate -Cert $cert -FilePath rakez-codesign.pfx -Password $pwd
Export-Certificate  -Cert $cert -FilePath rakez-codesign.cer
```

## CI signing

`build-windows.yml` imports a PFX from two repository secrets and signs `Rakez.exe` right
after PyInstaller and the installer right after Inno Setup. Without the secrets the build
simply stays unsigned.

```powershell
# One-time setup (PowerShell, from the repository root)
$pfx = "$env:USERPROFILE\.rakez\signing\rakez-codesign.pfx"
[Convert]::ToBase64String([IO.File]::ReadAllBytes($pfx)) | Set-Content pfx.b64 -NoNewline

gh secret set SIGNING_PFX_BASE64   < pfx.b64
gh secret set SIGNING_PFX_PASSWORD < "$env:USERPROFILE\.rakez\signing\pfx-password.txt"
Remove-Item pfx.b64
```

Rotate the certificate by exporting a new PFX and repeating the two `gh secret set` calls.

---

## العربية — توقيع الكود

الملفان `Rakez.exe` و`Rakez-Setup-<version>.exe` موقّعان بتوقيع Authenticode باسم
**Mostafa Elwakil** (شهادة ذاتية التوقيع، RSA 3072، SHA-256، صالحة حتى 2029-11-26، مع
Timestamp من DigiCert).

- **حدود الشهادة الذاتية:** لا تُزيل تحذير SmartScreen عند من لم يثبّت الشهادة؛ لإزالة التحذير
  للجميع تحتاج شهادة Code Signing مدفوعة (OV/EV) أو Azure Trusted Signing. البنية جاهزة:
  استبدل ملف PFX بنفس الأسرار فقط.
- **الثقة محليًا:** ثبّت `rakez-codesign.cer` في `Trusted Root` و`Trusted Publisher` عبر
  `certutil -f -user -addstore`، فيصبح التوقيع `Valid` ويظهر الاسم في نافذة UAC.
- **التوقيع محليًا:** `powershell -ExecutionPolicy Bypass -File packaging\sign_windows.ps1 -Path dist\Rakez.exe,dist\Rakez-Setup-*.exe`
- **في CI:** أضف السرّين `SIGNING_PFX_BASE64` و`SIGNING_PFX_PASSWORD` في إعدادات المستودع،
  وسيوقّع سير العمل الملفين تلقائيًا عند كل إصدار.
