import { Button, Result } from "antd";
import { useLocation, useNavigate } from "react-router-dom";

export function NotFoundPage() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <Result
      status="404"
      title="页面不存在"
      subTitle={`路径 ${location.pathname} 不存在或尚未开放`}
      extra={
        <Button type="primary" onClick={() => navigate("/")}>
          返回首页
        </Button>
      }
    />
  );
}
