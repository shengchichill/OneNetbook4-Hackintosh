/*
 * 亮度鍵（Fn+F4 調暗 / Fn+F5 調亮）在 macOS 下轉成 PS/2 亮度鍵。
 * 2026-11-05 Fedora 實測：按鍵觸發 EC GPE 0x6E → _Q04（BRTN 0x87，調暗）/ _Q05（BRTN 0x86，調亮），
 * 是 ACPI video 事件，不是鍵盤掃描碼。macOS 不處理 GFX0.DD1F 的 Notify，
 * 改成 Notify(PS2K, 0x0405/0x0406)，由 VoodooPS2Keyboard 轉成 e005/e006（亮度減/增）。
 * 配對 config.plist 的 ACPI patch：_Q04→XQ04、_Q05→XQ05（DSDT 內各唯一）。
 * 用的是 \_SB.PC00.LPCB.PS2K（另一個 \_SB.PC00.PS2K 的 _STA 回 0）。
 */
DefinitionBlock ("", "SSDT", 2, "ONB4", "BrtKey", 0x00000000)
{
    External (_SB_.PC00.LPCB.H_EC, DeviceObj)
    External (_SB_.PC00.LPCB.H_EC.XQ04, MethodObj)
    External (_SB_.PC00.LPCB.H_EC.XQ05, MethodObj)
    External (_SB_.PC00.LPCB.PS2K, DeviceObj)

    Scope (\_SB.PC00.LPCB.H_EC)
    {
        Method (_Q04, 0, NotSerialized)  // Fn+F4 調暗
        {
            If (_OSI ("Darwin"))
            {
                Notify (\_SB.PC00.LPCB.PS2K, 0x0405)
            }
            Else
            {
                \_SB.PC00.LPCB.H_EC.XQ04 ()
            }
        }

        Method (_Q05, 0, NotSerialized)  // Fn+F5 調亮
        {
            If (_OSI ("Darwin"))
            {
                Notify (\_SB.PC00.LPCB.PS2K, 0x0406)
            }
            Else
            {
                \_SB.PC00.LPCB.H_EC.XQ05 ()
            }
        }
    }
}
