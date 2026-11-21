"""Bounded resource transactions shared by custom mechanic adapters."""
SOURCE=r'''
typedef struct {int value,limit;} PortResource;
static void Port_ResourceReset(PortResource *r,int limit){r->value=0;r->limit=limit<0 ? 0 : limit;}
static int Port_ResourceAdd(PortResource *r,int amount)
{
    if(amount<0)amount=0;
    if(amount>r->limit-r->value)amount=r->limit-r->value;
    r->value+=amount;return amount;
}
static int Port_ResourceSpend(PortResource *r,int amount)
{
    if(amount<0 || amount>r->value)return 0;
    r->value-=amount;return 1;
}
'''
