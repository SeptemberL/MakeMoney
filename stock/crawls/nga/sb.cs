public interface ObjectPoolProxy
{
    void ReleaseAllCache();
    string ToString();
}

public class ScriptObjectPoolProxy<T> : ObjectPoolProxy where T : class, IPoolable
{
    private Stack<T> _poolStack = new Stack<T>();
    public Func<T> Constructor;

    public ScriptObjectPoolProxy()
    {
        ObjectPoolManager.AddObjectPool(this, false);
    }
}


public enum GraphNodeType
{
    None, 
    Default,
    FlowNode,
    EventNode
}

public enum EMiyabiNodeStatusType
{
    None,
    EditorBuildIn = 1000,//内置节点，仅编辑器使用，代码不导出，但是右键可创建
    EditorOnly = 1, //策划可修改，代码不导出
    Todo = 10, //待开发，导出代码
    ToBeReviewed = 2, //待验收
    Done = 3, //已验收
    Abandoned = 4, //已废弃
    Iteration = 5, //迭代中
}

