/* libgcc multiply and divide, halfwords, signed bytes, structs and memcpy. */
struct point {
    short x, y;
    signed char tag;
    int weight;
};

static volatile struct point out;
static char text[12];

static int to_text(int value)
{
    int len = 0;
    unsigned int v = value < 0 ? -value : value;
    do {
        text[len++] = '0' + v % 10;
        v /= 10;
    } while (v);
    if (value < 0)
        text[len++] = '-';
    return len;
}

int main(void)
{
    struct point a = { -1234, 321, -7, 100000 };
    struct point b = a;
    int total = 0;
    for (int i = 1; i < 12; i++) {
        b.x += i * 37;
        b.weight = b.weight / 3 + a.weight % (i + 1);
        total += b.x * b.tag + b.weight;
    }
    out.x = b.x;
    out.y = b.y;
    out.tag = b.tag;
    out.weight = b.weight;
    return total * 100 + to_text(total);
}
