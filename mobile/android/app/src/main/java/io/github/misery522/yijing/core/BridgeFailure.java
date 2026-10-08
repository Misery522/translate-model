package io.github.misery522.yijing.core;

/** 桥接错误只有受控码，不携带原异常、地址、正文或堆栈原因。 */
public final class BridgeFailure extends RuntimeException {
    private static final long serialVersionUID = 1L;
    public final String code;
    public final int status;
    public final boolean retryable;

    public BridgeFailure(String code, int status, boolean retryable) {
        super(code, null, false, false);
        this.code = code;
        this.status = status;
        this.retryable = retryable;
    }
}
