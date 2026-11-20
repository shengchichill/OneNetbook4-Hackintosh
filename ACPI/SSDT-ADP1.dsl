/*
 * AC adapter（ADP1）在 macOS 下啟用。
 * DSDT 的 ADP1._STA 只在 \ECON == 1 時回 0x0F，但這台韌體 ECON = 0（Linux 也看不到 AC），
 * 結果 ADP1 不存在 → SMCBatteryManager probe 要求「電池與 AC 都要有」→ 整個不啟動，電池也跟著沒了。
 * 配對 config.plist 的 ACPI patch：ADP1._STA 改名 XSTA（find 含 ECON 判斷，DSDT 內唯一）。
 * _PSR 原本就直接讀 EC 的 ECWR bit0，可用；插拔時 EC _Q0A 會 Notify(ADP1, 0x80)。
 */
DefinitionBlock ("", "SSDT", 2, "ONB4", "ADP1", 0x00000000)
{
    External (_SB_.PC00.LPCB.H_EC.ADP1, DeviceObj)
    External (_SB_.PC00.LPCB.H_EC.ADP1.XSTA, MethodObj)

    Scope (\_SB.PC00.LPCB.H_EC.ADP1)
    {
        Method (_STA, 0, NotSerialized)
        {
            If (_OSI ("Darwin")) { Return (0x0F) }
            Return (\_SB.PC00.LPCB.H_EC.ADP1.XSTA ())
        }
    }
}
