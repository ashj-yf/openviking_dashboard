import { Button, Result } from "antd";
import { useNavigate } from "react-router-dom";

export function ForbiddenPage() {
  const navigate = useNavigate();
  return (
    <Result
      status="403"
      title="无权访问"
      subTitle="当前账号没有访问该页面的权限；如需开通请联系平台管理员或团队管理员。"
      extra={
        <Button type="primary" onClick={() => navigate("/")}>
          返回首页
        </Button>
      }
    />
  );
}
