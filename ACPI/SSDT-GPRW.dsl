/* 修正 USB/LAN 造成的睡眠立即喚醒：GPRW -> XPRW 改名後，對 0x6D/0x0D 回報不可從 S3 喚醒 */
DefinitionBlock ("", "SSDT", 2, "ONB4", "Gprw", 0x00000000)
{
    External (XPRW, MethodObj)
    Method (GPRW, 2, NotSerialized)
    {
        If (_OSI ("Darwin"))
        {
            If ((0x6D == Arg0)) { Return (Package (0x02) { 0x6D, Zero }) }
            If ((0x0D == Arg0)) { Return (Package (0x02) { 0x0D, Zero }) }
        }
        Return (XPRW (Arg0, Arg1))
    }
}
