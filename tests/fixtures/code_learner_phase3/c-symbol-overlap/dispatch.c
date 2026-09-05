static int shared_decode(int value)
{
    return value > 0 ? value : 0;
}

int receive_message(int value)
{
    return shared_decode(value);
}

int receive_control(int value)
{
    return shared_decode(value) + 1;
}
