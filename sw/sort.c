/* Quicksort on pseudo-random data: branches, array indexing, every store visible. */
#define N 40

static unsigned int data[N];

static void sort(unsigned int *a, int lo, int hi)
{
    if (lo >= hi)
        return;
    unsigned int pivot = a[(lo + hi) / 2];
    int i = lo, j = hi;
    while (i <= j) {
        while (a[i] < pivot)
            i++;
        while (a[j] > pivot)
            j--;
        if (i <= j) {
            unsigned int t = a[i];
            a[i++] = a[j];
            a[j--] = t;
        }
    }
    sort(a, lo, j);
    sort(a, i, hi);
}

int main(void)
{
    unsigned int x = 2463534242u;
    for (int i = 0; i < N; i++) {
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
        data[i] = x;
    }
    sort(data, 0, N - 1);
    for (int i = 1; i < N; i++)
        if (data[i - 1] > data[i])
            return -1;
    return data[N / 2];
}
