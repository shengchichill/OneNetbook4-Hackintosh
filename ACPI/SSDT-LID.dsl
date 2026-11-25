/*
 * 闔蓋在 macOS 下不會睡眠的修正（2026-11-24）。
 * 原廠 EC 事件 _Q0C/_Q0D 與 LID0._LID 都用 ECRD(RefOf(LSTE)) 讀闔蓋狀態，
 * macOS 的 ACPICA（20160930）執行 ECRD 回報 AE_AML_OPERAND_TYPE，方法中止，
 * Notify(LID0, 0x80) 永遠沒送出（ONB4 lid-acpi-20261124-2.log）。Fedora 正常。
 * Darwin 下改成直接讀 EC 欄位 LSTE（1 = 開蓋），並通知 LID0。
 * 刻意不呼叫 GFX0.GLID：它在 macOS 從未成功執行過，加進來會多一個顯示驅動變因。
 * 配對 config.plist 的 ACPI patch：_Q0C→XQ0C、_Q0D→XQ0D、LID0._LID→XLID（DSDT 內各唯一）。
 */
DefinitionBlock ("", "SSDT", 2, "ONB4", "LidFix", 0x00000000)
{
    External (_SB_.PC00.LPCB.H_EC, DeviceObj)
    External (_SB_.PC00.LPCB.H_EC.LSTE, FieldUnitObj)
    External (_SB_.PC00.LPCB.H_EC.LID0, DeviceObj)
    External (_SB_.PC00.LPCB.H_EC.XQ0C, MethodObj)
    External (_SB_.PC00.LPCB.H_EC.XQ0D, MethodObj)
    External (_SB_.PC00.LPCB.H_EC.LID0.XLID, MethodObj)

    Scope (\_SB.PC00.LPCB.H_EC)
    {
        Method (_Q0C, 0, NotSerialized)  // 闔蓋／開蓋事件
        {
            If (_OSI ("Darwin"))
            {
                Notify (\_SB.PC00.LPCB.H_EC.LID0, 0x80)
            }
            Else
            {
                \_SB.PC00.LPCB.H_EC.XQ0C ()
            }
        }

        Method (_Q0D, 0, NotSerialized)  // 闔蓋／開蓋事件
        {
            If (_OSI ("Darwin"))
            {
                Notify (\_SB.PC00.LPCB.H_EC.LID0, 0x80)
            }
            Else
            {
                \_SB.PC00.LPCB.H_EC.XQ0D ()
            }
        }
    }

    Scope (\_SB.PC00.LPCB.H_EC.LID0)
    {
        Method (_LID, 0, NotSerialized)
        {
            If (_OSI ("Darwin"))
            {
                Return (\_SB.PC00.LPCB.H_EC.LSTE)
            }

            Return (\_SB.PC00.LPCB.H_EC.LID0.XLID ())
        }
    }
}
