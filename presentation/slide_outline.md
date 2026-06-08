# 二手交易 AI 防踩雷助理：7 頁簡報大綱

1. 封面：FB/Threads 二手交易 AI 防踩雷助理。
2. 動機與目的：二手交易從「買便宜」變成「先判斷可不可信」。
3. 生活痛點：假買家、假客服、金流驗證、釣魚物流連結、私下加 LINE。
4. 方法流程：Webhook/Form -> VLM -> pseudo-query -> HyDE -> RAG -> LLM -> n8n 自動化。
5. 技術對應：RAG、pseudo-query、HyDE、VLM、LLM、n8n 各自負責什麼。
6. 預期結果：低/中/高風險案例、輸出格式、測試結果 3/3 通過。
7. 結論與未來應用：可做為學生、家人、社團買賣的風險提醒工具。

## 主要參考來源

- n8n RAG in n8n: https://docs.n8n.io/advanced-ai/rag-in-n8n/
- n8n AI Agent: https://docs.n8n.io/integrations/builtin/cluster-nodes/root-nodes/n8n-nodes-langchain.agent/
- n8n Google Gemini node: https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-langchain.googlegemini/
- LangChain HyDE retriever: https://docs.langchain.com/oss/javascript/integrations/retrievers/hyde/
- 165 防詐公告整理: https://www.vac.gov.tw/cp-2181-155221-1.html
- 二手交易賣家詐騙新聞資料: https://news.immigration.gov.tw/NewsSection/Detail/a70e7756-68e8-4aef-b448-075936689782?category=0&lang=TW
- 警政署假賣貨便/假客服提醒: https://wwwcdn.npa.gov.tw/ch/app/news/view?id=2139&module=news&serno=1ff19028-1e0e-4b6e-908d-32a28051caa2
