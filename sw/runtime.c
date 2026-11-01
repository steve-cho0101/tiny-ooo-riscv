/* GCC can call these even with -ffreestanding, and libgcc does not supply them. */
typedef unsigned int size_t;

void *memset(void *dest, int value, size_t count)
{
    unsigned char *d = dest;
    while (count--)
        *d++ = (unsigned char)value;
    return dest;
}

void *memcpy(void *dest, const void *src, size_t count)
{
    unsigned char *d = dest;
    const unsigned char *s = src;
    while (count--)
        *d++ = *s++;
    return dest;
}

void *memmove(void *dest, const void *src, size_t count)
{
    unsigned char *d = dest;
    const unsigned char *s = src;
    if (d < s)
        return memcpy(dest, src, count);
    while (count--)
        d[count] = s[count];
    return dest;
}

int memcmp(const void *a, const void *b, size_t count)
{
    const unsigned char *x = a, *y = b;
    for (size_t i = 0; i < count; i++)
        if (x[i] != y[i])
            return x[i] - y[i];
    return 0;
}
