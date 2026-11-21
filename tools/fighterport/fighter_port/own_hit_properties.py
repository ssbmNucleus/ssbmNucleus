"""Native hit-property conversions for adapters that modify active hitboxes."""

SHIELD = r'''
// Match the script writer's signed-byte range and nearest/even rounding.
// Always pass an immutable source offset or a freshly computed effective value.
static int Native_ShieldField(float value)
{
    int whole; float fraction;
    if(value>=127)return 127;
    if(value<=-128)return -128;
    whole=(int)value;fraction=value-whole;
    if(fraction>0.5f || (fraction==0.5f && whole%2))whole++;
    else if(fraction<-0.5f || (fraction==-0.5f && whole%2))whole--;
    return whole;
}
'''
