/* 停用 AWAC，改用傳統 RTC（DSDT 以 STAS 切換） */
DefinitionBlock ("", "SSDT", 2, "ONB4", "AwacOff", 0x00000000)
{
    External (STAS, IntObj)
    Scope (_SB)
    {
        Method (_INI, 0, NotSerialized)
        {
            If (_OSI ("Darwin")) { STAS = One }
        }
    }
}
