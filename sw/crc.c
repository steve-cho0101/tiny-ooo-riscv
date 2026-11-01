/* CRC-32 over a string: bytes from .rodata, shifts, table-free bit loops. */
static const char message[] = "The quick brown fox jumps over the lazy dog";

int main(void)
{
    unsigned int crc = 0xFFFFFFFFu;
    for (const char *p = message; *p; p++) {
        crc ^= (unsigned char)*p;
        for (int bit = 0; bit < 8; bit++)
            crc = (crc >> 1) ^ (0xEDB88320u & -(crc & 1));
    }
    return ~crc;
}
