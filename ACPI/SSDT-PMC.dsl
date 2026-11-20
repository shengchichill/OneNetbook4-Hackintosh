/* 400/500 系列 PCH 需要 PMC MMIO 讓原生 NVRAM 正常 */
DefinitionBlock ("", "SSDT", 2, "ONB4", "PmcR", 0x00001000)
{
    External (_SB_.PC00.LPCB, DeviceObj)
    Scope (\_SB.PC00.LPCB)
    {
        Device (PMCR)
        {
            Name (_HID, EisaId ("APP9876"))
            Method (_STA, 0, NotSerialized)
            {
                If (_OSI ("Darwin")) { Return (0x0B) }
                Return (Zero)
            }
            Name (_CRS, ResourceTemplate ()
            {
                Memory32Fixed (ReadWrite, 0xFE000000, 0x00010000)
            })
        }
    }
}
