int encode_packet(int value)
{
    return value << 1;
}

int audit_packet(int value)
{
    return value >= 0;
}
