class FlowPortAsyncOut : FlowPort
{
    public static FlowPortAsyncOut CreateAsync()
    {
        return new FlowPortAsyncOut();
    }

    protected override bool IsInput => false;

    public bool HasOutput(in GrphNodeContext nodeContext)
    {
        var portId = GetPortId(nodeContext);
        if(portId == 0)
            return false;
        var graphContext = nodeContext.GraphContext;
        if(graphContext == null)
            return false;
        var connection = graphContext.PrototypeData.FindConnectionByFlowOut(portId);
        return connection.IsValid;
    }

    public void AsyncCallNode(in GraphNodeContext leaveNodeContext)
    {
        GraphUtils.AsyncCallNode(leaveNodeContext, GetPortId(leaveNodeContext));
    }
    
}

public interface IGraphSerializer
{
    JosnNode ToJson();
    void FromJson(JsonNode reader);
}

public struct GraphValueType : IGraphSerializer, IEquatable<GraphValueType>
{
    public static readonly GraphValueType Empty = new GraphValueType();

    public bool IsDataType => !string.IsNullOrEmpty(MainType);
    public bool IsNested => TypeTag == 1;

}

public interface IValueHolder
{
    ScriptDataType DataType { get; }
    GraphValueType ValueType { get; }
    System.Object ToObject();
    TableUnionValue ToUnionValue();
    bool Equals(IValueHolder other);
}

public static class ValueHolderHelper
{
    public static bool TryGetValue<T>(this IValueHolder valueHolder, out T value)
    {
        var realHolder = valueHolder as IValueHolder<T>;
        if(realHolder != null)
        {
            value = realHolder.Value;
            return true;
        }
        value = default(T);
        return false;
    }

    public static GraphUnionValue ToUnionValue(GraphValueFormat valueFormat)
    {
        if(valueFormat == null)
            return GraphUnionValue.Nullable;

        if(valueFormat.value == null)
        {
            var type = valueFormat.Type;
            if(!type.IsDataType)
                return GraphUnionValue.Nullable;
            GraphUnionValue.CastFromValue(type, GraphTypeOperatorMap.GetGraphTypeOperator(type).GetDefaultValue(type));

        }
        return GraphUnionValue.CastFromValue(valueFormat.Value);
    }

    public static IValueHolder CreateValueHolder(in GraphValueType valueType, object o, bool logNotDefined = true)
    {
        var typeOp = GraphTypeOperatorMap.GetGraphTypeOperator(valueType, logNotDefined);
        return typeOp?.CreateValueHolder(valueType, o);
    }
}

public class ValueHolder<T> : IValueHolder
{
    public ScriptDataType DataType {get; private set;}
    public GraphValueType ValueType {get; private set;}
    public T Value {get; protected set;}

    public ValueHolder(in GraphValueType valueType, T value)
    {
        DataType = valueType.ToDataType();
        ValueType = valueType;
        Value = value;
    }

    public Object ToObject()
    {
        return Value;
    }

    public TableUnionValue ToUnionValue()
    {
        return GraphUnionValue.CastFrom(Value);
    }

    public bool Equals(IValueHolder other)
    {
        //AI
        if(ReferenceEquals(other, this))
            return true;
        if(ReferenceEquals(other, null))
            return false;
        if(other.DataType != DataType)
            return false;
        if(other.ValueType != ValueType)
            return false;
        return Value.Equals(other.Value);
    }

    public override string ToString()
    {
        return $"valueType:{VlaueType}, value {Value}";
    }


}

public class GraphBlackboardOverride 
{
    public class OverrideInfo
    {
        public int dynamicPortId;
        public string blackboardName;
        public OverrideInfo(int dynamicPortId, string blackboardName)
        {
            this.dynamicPortId = dynamicPortId;
            this.blackboardName = blackboardName;
        }
    }

    private MultiDictionary<int, OverrideInfo> overrideInfos = new MultiDictionary<int, OverrideInfo>();

    public bool TryGetOverrideInfo(int dynamicPortId, out OverrideInfo overrideInfo)
    {
        return overrideInfos.TryGetValue(dynamicPortId, out overrideInfo);
    }
    public void AddOverrideInfo(int dynamicPortId, string blackboardName)
    {
        overrideInfos.Add(dynamicPortId, new OverrideInfo(dynamicPortId, blackboardName));
    }
    public void RemoveOverrideInfo(int dynamicPortId)
    {
        overrideInfos.Remove(dynamicPortId);
    }

}

public class GraphDetail
{
    public string GraphName;
    public GraphType GraphType;
    public List<NodeFormat> NodeInfos = new List<NodeFormat>();
    public GraphBlackboardOverride graphOverrideBlackboard = null;
    public GraphVariable GraphVariables = null;
    public List<GraphKnot> GraphKnots = null;
}