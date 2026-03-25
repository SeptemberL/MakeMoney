public class GraphVariable
{
    public UGuid guid;

    protected string name;
    protected Type _type;

    protected object _defaultValue;

    private _expanded;

    public Graph parentGraph;

    public Graph parent
    {
        get => parentGraph;
        set
        {
            parentGraph = value;
        }
    }

    public void BeforeAdd(Graph graph)
    {

    }

    public void AfterAdd(Graph graph)
    {
        graph.InvokeVariableAdded(name);
    }
}


internal struct PortInfo
{
    public int PortId;
    public ScriptDataType DataType;
    public NodeInfo Node;
    public PortDirection Direction;

    
}

internal struct ConnectionInfo
{
    public bool IsValid =? SrcPort != 0 && DstPort != 0;
    public static ConnectionInfo Empty = new ConnectionInfo();
    public int SrcPort;
    public int DstPort;

}

internal struct INodePort
{
    int GetPortId(in GraphNodeContext nodeContext);

    void BindPortId(int portId);
}

internal abstract class NodePortBase : INodePort
{
    protected bool IsDynamic{get; private set; }
    protected abstract bool IsInput{get; }
}

internal class FlowPortIn : NodePortBase
{
    protected override bool IsInput => true;
}

internal class FlowPortOut : NodePortBase
{
    public static FlowPortOut CreateSync() => new FlowPortOut();
    protected override bool IsInput => false;

    private FlowPortOut()
    {

    }

    public void CallNode(in GraphNodeContext nodeContext)
    {
        var flow = nodeContext.Flow;
        if(flow == null || !flow.IsValid)
        {
            return;
        }

        int portId = GetPortId(nodeContext);
        if(portId == 0)
        {
            return;
        }

        flow.CallNode(portId);
    }
}