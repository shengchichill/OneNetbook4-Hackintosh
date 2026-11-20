/* 內建螢幕背光（Coffee Lake 以後 _UID = 0x13） */
DefinitionBlock ("", "SSDT", 2, "ONB4", "Pnlf", 0x00000000)
{
    External (_SB_.PC00.GFX0, DeviceObj)
    Scope (\_SB.PC00.GFX0)
    {
        Device (PNLF)
        {
            Name (_HID, EisaId ("APP0002"))
            Name (_CID, "backlight")
            Name (_UID, 0x13)
            Method (_STA, 0, NotSerialized)
            {
                If (_OSI ("Darwin")) { Return (0x0B) }
                Return (Zero)
            }
        }
    }
}
