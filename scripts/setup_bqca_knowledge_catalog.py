#!/usr/bin/env python3
"""
Provision & synchronize BigQuery Knowledge Catalog (Dataplex Universal Catalog)
metadata, Business Glossary terms, and the BigQuery Conversational Analytics (BQCA)
Data Agent (`bhi-manu-2026-agent`) for `cliu201-477811.bhi_manu`.
"""

import json
import sys
import time
from typing import Any, Dict, List

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud import bigquery

PROJECT_ID = "cliu201-477811"
DATASET_ID = "bhi_manu"
LOCATION = "global"
DATA_AGENT_ID = "bhi-manu-2026-agent"
GLOSSARY_ID = "bhi-manu-2026-glossary"

# ============================================================================
# 1. Knowledge Catalog Table & Column Semantic Metadata Definitions
# ============================================================================

TABLE_SPECS: Dict[str, Dict[str, Any]] = {
    "customer_revenue_scorecard_2026": {
        "description": (
            "【BHI Manufacturing 2026 客户级收入与 Run Rate 计分卡】"
            "按客户 (Account / reporting_id) 汇总 2026 年 YTD 累计收入（GCP 总盘、Cloud AI、DA 数据分析、DB 数据库、GE）、"
            "最新出账日单日 RunRate (Latest DRR)、近 7 日平均 DRR、当月累计 RunRate (Current Month MTD MRR)、"
            "上月完整自然月累计 RunRate (Prior Month Full MRR，即 2026-09) 及 Cloud AI 渗透率。同时提供 RVP 销售认账口径与 Gross 毛出账口径。"
        ),
        "synonyms": ["客户计分卡", "客户收入汇总表", "Account Scorecard", "Customer Revenue Scorecard"],
        "tags": ["scorecard", "customer", "account", "rvp", "gross", "drr", "mrr", "plan2100"],
        "columns": {
            "reporting_id": "客户唯一 Reporting ID 标识符（关联键）",
            "account_name": "客户英文/标准名称（Account Name）",
            "nal_name": "所属一线销售 NAL 业务组名称（含负责人 LDAP，如 Mobile ENT Manu (wendylv)）",
            "total_gcp_gross_rev": "2026 YTD GCP 整体毛消费出账收入 (Gross Revenue, USD)",
            "total_gcp_rvp_rev": "2026 YTD GCP 整体销售认账收入 (RVP Revenue, USD，Bucket 1 口径基础)",
            "total_cloud_ai_gross_rev": "2026 YTD Cloud AI 毛消费收入 (Gross Revenue, USD，含 AI_SOLUTIONS + DEVELOPER_AI_ASSISTANCE)",
            "total_cloud_ai_rvp_rev": "2026 YTD Cloud AI 销售认账收入 (RVP Revenue, USD，Bucket 2 核心组成部分)",
            "total_da_gross_rev": "2026 YTD 数据分析 (DA: ANALYTICS + LOOKER) 毛消费收入 (Gross Revenue, USD)",
            "total_da_rvp_rev": "2026 YTD 数据分析 (DA: ANALYTICS + LOOKER) 销售认账收入 (RVP Revenue, USD，Bucket 2 组成部分)",
            "total_db_gross_rev": "2026 YTD 数据库 (DB: MIGRATE_AND_MODERNIZE_DATABASES) 毛消费收入 (Gross Revenue, USD)",
            "total_db_rvp_rev": "2026 YTD 数据库 (DB: MIGRATE_AND_MODERNIZE_DATABASES) 销售认账收入 (RVP Revenue, USD，Bucket 2 组成部分)",
            "total_ge_gross_rev": "2026 YTD Gemini Enterprise 账单消费毛收入 (Gross Revenue, USD；注：GE 考核请查 customer_ge_bookings_2026 签约表)",
            "total_ge_rvp_rev": "2026 YTD Gemini Enterprise 账单消费认账收入 (RVP Revenue, USD)",
            "active_days": "2026 年内有实际云消费出账的活跃天数",
            "latest_gcp_gross_drr": "最新出账日单日 GCP 毛消费 RunRate (Latest Daily Gross DRR, USD/day)",
            "latest_7d_avg_gcp_gross_drr": "最新 7 日日均 GCP 毛消费 RunRate (7-Day Avg Gross DRR, USD/day)",
            "latest_gcp_rvp_drr": "最新出账日单日 GCP 销售认账 RunRate (Latest Daily RVP DRR, USD/day)",
            "latest_7d_avg_gcp_rvp_drr": "最新 7 日日均 GCP 销售认账 RunRate (7-Day Avg RVP DRR, USD/day)",
            "latest_cloud_ai_gross_drr": "最新出账日单日 Cloud AI 毛消费 RunRate (USD/day)",
            "latest_7d_avg_cloud_ai_gross_drr": "最新 7 日日均 Cloud AI 毛消费 RunRate (USD/day)",
            "latest_cloud_ai_rvp_drr": "最新出账日单日 Cloud AI 销售认账 RunRate (USD/day)",
            "latest_7d_avg_cloud_ai_rvp_drr": "最新 7 日日均 Cloud AI 销售认账 RunRate (USD/day)",
            "latest_da_gross_drr": "最新出账日单日 DA 数据分析毛消费 RunRate (USD/day)",
            "latest_7d_avg_da_gross_drr": "最新 7 日日均 DA 数据分析毛消费 RunRate (USD/day)",
            "latest_da_rvp_drr": "最新出账日单日 DA 数据分析销售认账 RunRate (USD/day)",
            "latest_7d_avg_da_rvp_drr": "最新 7 日日均 DA 数据分析销售认账 RunRate (USD/day)",
            "latest_db_gross_drr": "最新出账日单日 DB 数据库毛消费 RunRate (USD/day)",
            "latest_7d_avg_db_gross_drr": "最新 7 日日均 DB 数据库毛消费 RunRate (USD/day)",
            "latest_db_rvp_drr": "最新出账日单日 DB 数据库销售认账 RunRate (USD/day)",
            "latest_7d_avg_db_rvp_drr": "最新 7 日日均 DB 数据库销售认账 RunRate (USD/day)",
            "latest_ge_gross_drr": "最新出账日单日 GE 账单毛 RunRate (USD/day)",
            "latest_7d_avg_ge_gross_drr": "最新 7 日日均 GE 账单毛 RunRate (USD/day)",
            "latest_ge_rvp_drr": "最新出账日单日 GE 账单认账 RunRate (USD/day)",
            "latest_7d_avg_ge_rvp_drr": "最新 7 日日均 GE 账单认账 RunRate (USD/day)",
            "current_month_gcp_gross_mrr": "当月 (2026-10 MTD) 自然日累计 GCP Gross MRR (USD)",
            "current_month_gcp_rvp_mrr": "当月 (2026-10 MTD) 自然日累计 GCP RVP MRR (USD)",
            "current_month_cloud_ai_gross_mrr": "当月 (2026-10 MTD) 自然日累计 Cloud AI Gross MRR (USD)",
            "current_month_cloud_ai_rvp_mrr": "当月 (2026-10 MTD) 自然日累计 Cloud AI RVP MRR (USD)",
            "current_month_da_gross_mrr": "当月 (2026-10 MTD) 自然日累计 DA Gross MRR (USD)",
            "current_month_da_rvp_mrr": "当月 (2026-10 MTD) 自然日累计 DA RVP MRR (USD)",
            "current_month_db_gross_mrr": "当月 (2026-10 MTD) 自然日累计 DB Gross MRR (USD)",
            "current_month_db_rvp_mrr": "当月 (2026-10 MTD) 自然日累计 DB RVP MRR (USD)",
            "current_month_ge_gross_mrr": "当月 (2026-10 MTD) 自然日累计 GE Gross MRR (USD)",
            "current_month_ge_rvp_mrr": "当月 (2026-10 MTD) 自然日累计 GE RVP MRR (USD)",
            "prior_month_gcp_gross_mrr": "上月完整自然月 (2026-09) GCP Gross MRR (USD)",
            "prior_month_gcp_rvp_mrr": "上月完整自然月 (2026-09) GCP RVP MRR (USD)",
            "prior_month_cloud_ai_gross_mrr": "上月完整自然月 (2026-09) Cloud AI Gross MRR (USD)",
            "prior_month_cloud_ai_rvp_mrr": "上月完整自然月 (2026-09) Cloud AI RVP MRR (USD)",
            "prior_month_da_gross_mrr": "上月完整自然月 (2026-09) DA Gross MRR (USD)",
            "prior_month_da_rvp_mrr": "上月完整自然月 (2026-09) DA RVP MRR (USD)",
            "prior_month_db_gross_mrr": "上月完整自然月 (2026-09) DB Gross MRR (USD)",
            "prior_month_db_rvp_mrr": "上月完整自然月 (2026-09) DB RVP MRR (USD)",
            "prior_month_ge_gross_mrr": "上月完整自然月 (2026-09) GE Gross MRR (USD)",
            "prior_month_ge_rvp_mrr": "上月完整自然月 (2026-09) GE RVP MRR (USD)",
            "cloud_ai_gross_penetration_pct": "Cloud AI 毛收入占 GCP 毛收入渗透率百分比 (%)",
            "cloud_ai_rvp_penetration_pct": "Cloud AI RVP 认账收入占 GCP RVP 收入渗透率百分比 (%)",
        },
    },
    "nal_revenue_scorecard_2026": {
        "description": (
            "【BHI Manufacturing 2026 NAL 级收入与 Run Rate 汇总计分卡】"
            "按 12 个一线销售 NAL 业务组汇总客户数、2026 YTD 累计收入（GCP、Cloud AI、DA、DB 以及 Bucket 2 合计 dadbai）、"
            "最新单日 DRR、当月/上月 MRR 与 AI 渗透率。"
        ),
        "synonyms": ["NAL 计分卡", "NAL 收入汇总表", "NAL Revenue Scorecard"],
        "tags": ["nal", "scorecard", "rvp", "gross", "drr", "mrr"],
        "columns": {
            "nal_name": "一线销售 NAL 业务组名称（含负责人 LDAP，如 Mobile ENT Manu (wendylv)）",
            "accounts_count": "该 NAL 下有收入的活跃客户数量",
            "total_gcp_gross_rev": "NAL 2026 YTD GCP 毛消费总收入 (USD)",
            "total_gcp_rvp_rev": "NAL 2026 YTD GCP 销售认账总收入 (RVP Revenue, USD)",
            "total_cloud_ai_gross_rev": "NAL 2026 YTD Cloud AI 毛消费总收入 (USD)",
            "total_cloud_ai_rvp_rev": "NAL 2026 YTD Cloud AI 销售认账总收入 (RVP Revenue, USD)",
            "total_da_gross_rev": "NAL 2026 YTD DA 数据分析毛消费总收入 (USD)",
            "total_da_rvp_rev": "NAL 2026 YTD DA 数据分析销售认账总收入 (RVP Revenue, USD)",
            "total_db_gross_rev": "NAL 2026 YTD DB 数据库毛消费总收入 (USD)",
            "total_db_rvp_rev": "NAL 2026 YTD DB 数据库销售认账总收入 (RVP Revenue, USD)",
            "latest_gcp_gross_drr": "NAL 最新出账日单日 GCP Gross DRR (USD/day)",
            "latest_gcp_rvp_drr": "NAL 最新出账日单日 GCP RVP DRR (USD/day)",
            "latest_cloud_ai_gross_drr": "NAL 最新出账日单日 Cloud AI Gross DRR (USD/day)",
            "latest_cloud_ai_rvp_drr": "NAL 最新出账日单日 Cloud AI RVP DRR (USD/day)",
            "latest_da_gross_drr": "NAL 最新出账日单日 DA Gross DRR (USD/day)",
            "latest_da_rvp_drr": "NAL 最新出账日单日 DA RVP DRR (USD/day)",
            "latest_db_gross_drr": "NAL 最新出账日单日 DB Gross DRR (USD/day)",
            "latest_db_rvp_drr": "NAL 最新出账日单日 DB RVP DRR (USD/day)",
            "current_month_gcp_gross_mrr": "NAL 当月 (2026-10 MTD) GCP Gross MRR (USD)",
            "current_month_gcp_rvp_mrr": "NAL 当月 (2026-10 MTD) GCP RVP MRR (USD)",
            "prior_month_gcp_gross_mrr": "NAL 上月完整月 (2026-09) GCP Gross MRR (USD)",
            "prior_month_gcp_rvp_mrr": "NAL 上月完整月 (2026-09) GCP RVP MRR (USD)",
            "total_dadbai_gross_rev": "NAL 2026 YTD Bucket 2 (DA + DB + Cloud AI) 毛消费合计 (USD)",
            "total_dadbai_rvp_rev": "NAL 2026 YTD Bucket 2 (DA + DB + Cloud AI) RVP 销售认账合计 (USD)",
            "cloud_ai_gross_penetration_pct": "NAL Cloud AI 毛收入渗透率 (%)",
            "cloud_ai_rvp_penetration_pct": "NAL Cloud AI RVP 认账收入渗透率 (%)",
        },
    },
    "customer_monthly_revenue": {
        "description": (
            "【BHI Manufacturing 2026 客户 × 自然月度 MRR 与日均 DRR 明细表】"
            "记录每个客户在 2026-01 至 2026-10 每个自然月（year_month）的自然月累计 RunRate (MRR) 与当月日均 RunRate (DRR Avg)，"
            "覆盖 GCP、Cloud AI、DA、DB、GE 五大产品维度（含 RVP 与 Gross 双口径），适用于月度环比 (MoM) 增长分析与趋势对比。"
        ),
        "synonyms": ["客户月度收入表", "月度 MRR 明细", "Monthly Revenue", "MoM Trend"],
        "tags": ["monthly", "mrr", "drr_avg", "mom", "customer", "trend"],
        "columns": {
            "year_month": "自然年月字符串，格式为 'YYYY-MM'（如 '2026-01' 至 '2026-10'）",
            "reporting_id": "客户唯一 Reporting ID",
            "account_name": "客户名称 (Account Name)",
            "nal_name": "所属一线销售 NAL 名称",
            "days_in_month": "该客户在该自然月内的活跃出账天数",
            "gcp_gross_mrr": "当月自然日累计 GCP Gross MRR (USD)",
            "gcp_rvp_mrr": "当月自然日累计 GCP RVP MRR (USD，默认月度收入口径)",
            "cloud_ai_gross_mrr": "当月自然日累计 Cloud AI Gross MRR (USD)",
            "cloud_ai_rvp_mrr": "当月自然日累计 Cloud AI RVP MRR (USD)",
            "da_gross_mrr": "当月自然日累计 DA 数据分析 Gross MRR (USD)",
            "da_rvp_mrr": "当月自然日累计 DA 数据分析 RVP MRR (USD)",
            "db_gross_mrr": "当月自然日累计 DB 数据库 Gross MRR (USD)",
            "db_rvp_mrr": "当月自然日累计 DB 数据库 RVP MRR (USD)",
            "ge_gross_mrr": "当月自然日累计 GE 账单消费 Gross MRR (USD)",
            "ge_rvp_mrr": "当月自然日累计 GE 账单消费 RVP MRR (USD)",
            "gcp_gross_drr_avg": "当月日均 GCP Gross DRR (USD/day)",
            "gcp_rvp_drr_avg": "当月日均 GCP RVP DRR (USD/day)",
            "cloud_ai_gross_drr_avg": "当月日均 Cloud AI Gross DRR (USD/day)",
            "cloud_ai_rvp_drr_avg": "当月日均 Cloud AI RVP DRR (USD/day)",
            "da_gross_drr_avg": "当月日均 DA Gross DRR (USD/day)",
            "da_rvp_drr_avg": "当月日均 DA RVP DRR (USD/day)",
            "db_gross_drr_avg": "当月日均 DB Gross DRR (USD/day)",
            "db_rvp_drr_avg": "当月日均 DB RVP DRR (USD/day)",
            "ge_gross_drr_avg": "当月日均 GE Gross DRR (USD/day)",
            "ge_rvp_drr_avg": "当月日均 GE RVP DRR (USD/day)",
            "cloud_ai_gross_penetration_pct": "当月 Cloud AI Gross 渗透率 (%)",
            "cloud_ai_rvp_penetration_pct": "当月 Cloud AI RVP 渗透率 (%)",
        },
    },
    "customer_daily_runrate": {
        "description": (
            "【BHI Manufacturing 2026 客户每日 Daily Run Rate (DRR) 曲线明细表】"
            "记录 2026-01-01 至今每一天 (usage_date) 每个客户在 GCP、Cloud AI、DA、DB、GE 上的单日 DRR、"
            "当月累计 MTD MRR 以及 7 日移动平均 DRR (7d_avg)，支持客户级和 NAL 级每日曲线下钻与异常异动检测。"
        ),
        "synonyms": ["单日 RunRate 表", "Daily Run Rate", "DRR 明细表", "每日消费曲线"],
        "tags": ["daily", "drr", "run_rate", "time_series", "curve"],
        "columns": {
            "usage_date": "消费出账日期 (DATE, YYYY-MM-DD)",
            "reporting_id": "客户唯一 Reporting ID",
            "account_name": "客户名称 (Account Name)",
            "nal_name": "所属一线销售 NAL 名称",
            "gcp_gross_drr": "当日 GCP Gross 单日 DRR (USD)",
            "gcp_rvp_drr": "当日 GCP RVP 销售认账单日 DRR (USD)",
            "cloud_ai_gross_drr": "当日 Cloud AI Gross 单日 DRR (USD)",
            "cloud_ai_rvp_drr": "当日 Cloud AI RVP 单日 DRR (USD)",
            "da_gross_drr": "当日 DA 数据分析 Gross 单日 DRR (USD)",
            "da_rvp_drr": "当日 DA 数据分析 RVP 单日 DRR (USD)",
            "db_gross_drr": "当日 DB 数据库 Gross 单日 DRR (USD)",
            "db_rvp_drr": "当日 DB 数据库 RVP 单日 DRR (USD)",
            "ge_gross_drr": "当日 GE Gross 单日 DRR (USD)",
            "ge_rvp_drr": "当日 GE RVP 单日 DRR (USD)",
            "year_month": "所属自然年月 ('YYYY-MM')",
            "gcp_gross_mrr_mtd": "截至当日的当月累计 GCP Gross MTD MRR (USD)",
            "gcp_gross_month_total_mrr": "所属自然月全月 GCP Gross MRR (USD)",
            "gcp_gross_drr_7d_avg": "截至当日的 7 日移动平均 GCP Gross DRR (USD/day)",
            "gcp_rvp_mrr_mtd": "截至当日的当月累计 GCP RVP MTD MRR (USD)",
            "gcp_rvp_month_total_mrr": "所属自然月全月 GCP RVP MRR (USD)",
            "gcp_rvp_drr_7d_avg": "截至当日的 7 日移动平均 GCP RVP DRR (USD/day)",
            "cloud_ai_gross_mrr_mtd": "截至当日的当月累计 Cloud AI Gross MTD MRR (USD)",
            "cloud_ai_gross_month_total_mrr": "所属自然月全月 Cloud AI Gross MRR (USD)",
            "cloud_ai_gross_drr_7d_avg": "7 日移动平均 Cloud AI Gross DRR (USD/day)",
            "cloud_ai_rvp_mrr_mtd": "截至当日的当月累计 Cloud AI RVP MTD MRR (USD)",
            "cloud_ai_rvp_month_total_mrr": "所属自然月全月 Cloud AI RVP MRR (USD)",
            "cloud_ai_rvp_drr_7d_avg": "7 日移动平均 Cloud AI RVP DRR (USD/day)",
            "da_gross_mrr_mtd": "截至当日的当月累计 DA Gross MTD MRR (USD)",
            "da_gross_month_total_mrr": "所属自然月全月 DA Gross MRR (USD)",
            "da_gross_drr_7d_avg": "7 日移动平均 DA Gross DRR (USD/day)",
            "da_rvp_mrr_mtd": "截至当日的当月累计 DA RVP MTD MRR (USD)",
            "da_rvp_month_total_mrr": "所属自然月全月 DA RVP MRR (USD)",
            "da_rvp_drr_7d_avg": "7 日移动平均 DA RVP DRR (USD/day)",
            "db_gross_mrr_mtd": "截至当日的当月累计 DB Gross MTD MRR (USD)",
            "db_gross_month_total_mrr": "所属自然月全月 DB Gross MRR (USD)",
            "db_gross_drr_7d_avg": "7 日移动平均 DB Gross DRR (USD/day)",
            "db_rvp_mrr_mtd": "截至当日的当月累计 DB RVP MTD MRR (USD)",
            "db_rvp_month_total_mrr": "所属自然月全月 DB RVP MRR (USD)",
            "db_rvp_drr_7d_avg": "7 日移动平均 DB RVP DRR (USD/day)",
            "ge_gross_mrr_mtd": "截至当日的当月累计 GE Gross MTD MRR (USD)",
            "ge_gross_month_total_mrr": "所属自然月全月 GE Gross MRR (USD)",
            "ge_gross_drr_7d_avg": "7 日移动平均 GE Gross DRR (USD/day)",
            "ge_rvp_mrr_mtd": "截至当日的当月累计 GE RVP MTD MRR (USD)",
            "ge_rvp_month_total_mrr": "所属自然月全月 GE RVP MRR (USD)",
            "ge_rvp_drr_7d_avg": "7 日移动平均 GE RVP DRR (USD/day)",
        },
    },
    "customer_ge_bookings_2026": {
        "description": (
            "【BHI Manufacturing 2026 Gemini Enterprise (GE) 客户签约合同明细表】"
            "源自 concord-prod.service_cloudbi.bookings，记录 2026 年所有签约 Gemini Enterprise 及 Gen AI FSP 的客户订单、"
            "SKU 描述、授权席位数 (Seats)、签约总合同额 (Signed TCV)、100% 原始年化签约额 (Signed ACV 合计 $768,127.39)、"
            "新签/扩容/续约拆分，以及按 go/plan2100 折算（100% GE + 10% FSP，剔除续约）后的水位线前净增签约额 (net_iacv 合计 $762,210.33)。"
        ),
        "synonyms": ["GE 客户签约表", "Gemini Enterprise 订单表", "GE Bookings"],
        "tags": ["ge", "gemini_enterprise", "bookings", "acv", "tcv", "seats", "bucket_3"],
        "columns": {
            "reporting_id": "签约客户唯一 Reporting ID",
            "account_name": "签约客户名称 (如 Huami, Inc.、Xiaomi、OPPO 等)",
            "nal_name": "所属一线销售 NAL 名称",
            "product_l3": "签约产品三级分类（'Gemini Enterprise' 按 100% 计入，'Gen AI FSP' 按 10% 计入）",
            "sku_description": "签约 SKU 详细产品与版本描述（如 Gemini Enterprise Standard / Plus）",
            "order_type": "订单类型 (New / Expansion / Renewal / Cancellation)",
            "booking_type": "Booking 记账类型",
            "deal_lines": "合同明细行数",
            "orders_count": "签约订单笔数",
            "total_seats": "签约授权总席位数 (Seats)",
            "first_booking_date": "首次签约日期 (DATE)",
            "latest_booking_date": "最近一次签约日期 (DATE，含 2026-10-08 华米新增签约)",
            "signed_tcv": "签约总合同金额 (Signed Total Contract Value, USD)",
            "signed_acv": "100% 原始签约年化合同金额 (Signed ACV, USD，全领地合计 $768,127.39)",
            "comp_new_acv": "新签年化金额 (New ACV, USD)",
            "comp_expansion_acv": "扩容年化金额 (Expansion ACV, USD)",
            "comp_renewal_acv": "续约年化金额 (Renewal ACV, USD，全领地合计 $4,159.62，不计入净增 Net ACV)",
            "raw_net_iacv": "未做 FSP 10% 权重折算前的净增 iACV (New + Expansion, USD)",
            "net_iacv": "按 go/plan2100 规则（剔除续约 + Gen AI FSP 按 10% 折算）计算的水位线冲减前净增 Net iACV (USD，全领地合计 $762,210.33)",
            "total_comp_acv": "计入薪酬核算口径的总 ACV (USD)",
        },
    },
    "nal_ge_bookings_2026": {
        "description": (
            "【BHI Manufacturing 2026 NAL 级 Gemini Enterprise (GE) 签约与 Rainmaker 认账汇总表】"
            "按 12 个一线销售 NAL 汇总 GE 签约客户数、订单数、席位数、100% 原始签约额 (signed_acv 合计 $768,127.39)、"
            "水位线前净增签约额 (raw_net_iacv 合计 $762,210.33)，以及扣除 NETACV_MONTHLY 水位线与退订冲减 (-$49,181.03) 后的 "
            "go/rainmaker 最终认账达成额 (net_iacv 合计 $713,029.30，其中 wendylv 为 $30,463.30)。"
        ),
        "synonyms": ["NAL GE 签约汇总表", "GE NAL 达成表", "NAL GE Bookings"],
        "tags": ["ge", "nal", "bookings", "rainmaker", "watermark", "bucket_3"],
        "columns": {
            "nal_name": "一线销售 NAL 业务组名称",
            "customers_count": "该 NAL 下已签约 GE 的客户数",
            "deal_lines": "合同明细行总数",
            "orders_count": "签约订单总笔数",
            "total_seats": "签约授权总席位数 (Seats)",
            "signed_tcv": "签约总合同额 (Signed TCV, USD)",
            "signed_acv": "100% 原始签约年化金额 (Signed ACV, USD，全领地合计 $768,127.39)",
            "comp_new_acv": "新签 ACV (USD)",
            "comp_expansion_acv": "扩容 Expansion ACV (USD)",
            "comp_renewal_acv": "续约 Renewal ACV (USD，合计 $4,159.62)",
            "raw_net_iacv": "水位线冲减前净增 Net iACV (100% GE + 10% FSP，剔除续约，全领地合计 $762,210.33)",
            "net_iacv": "go/rainmaker 最终官方认账达成 (NETACV_MONTHLY 扣除 fankaia 水位线 -$49,181.03 后，全领地合计 $713,029.30，wendylv 为 $30,463.30)",
            "total_comp_acv": "薪酬口径总 ACV (USD)",
            "latest_booking_date": "该 NAL 最近一次 GE 签约日期 (DATE)",
        },
    },
    "ge_monthly_bookings_2026": {
        "description": (
            "【BHI Manufacturing 2026 月度 Gemini Enterprise (GE) 签约走势汇总表】"
            "按自然月 (2026-01 至 2026-10) 汇总全领地 GE 签约客户数、席位数、Signed TCV、Signed ACV、新签/扩容/续约拆分及净增 Net iACV。"
        ),
        "synonyms": ["GE 月度签约趋势表", "Monthly GE Bookings"],
        "tags": ["ge", "monthly", "bookings", "trend"],
        "columns": {
            "year_month": "签约自然年月 ('YYYY-MM')",
            "deal_lines": "当月签约合同明细行数",
            "customers_count": "当月签约客户数",
            "monthly_seats": "当月签约总席位数 (Seats)",
            "signed_tcv": "当月签约总合同额 (Signed TCV, USD)",
            "signed_acv": "当月 100% 原始签约年化金额 (Signed ACV, USD)",
            "comp_new_acv": "当月新签 ACV (USD)",
            "comp_expansion_acv": "当月扩容 Expansion ACV (USD)",
            "comp_renewal_acv": "当月续约 Renewal ACV (USD)",
            "net_iacv": "当月折算后净增 Net iACV (USD)",
        },
    },
    "nal_three_buckets_quota_2026": {
        "description": (
            "【BHI Manufacturing 2026 12 个一线 NAL 三大考核桶 (Three Quota Buckets) 目标与达成总表】"
            "100% 对齐 go/rainmaker 与 concord-prod.service_cloudbi 官方考核口径，涵盖 12 个 Street-Level NAL 在三大桶的基线、Quota、实际达成与达成率：\n"
            "1. Bucket 1 (GCP iRevenue)：全领地 Quota $78,952,908.00，最新整体实际达成 $73,719,191.25 (达成率 93.37%)；其中 Strategic Sel Manu (wendylv) Quota 为 $18,407,282.00，最新实际达成 $18,426,974.50 (达成率 100.11%)。\n"
            "2. Bucket 2 (DA, DB & Cloud AI iRevenue)：全领地 Quota $51,653,090.00，最新整体实际达成 $41,668,607.68 (达成率 80.67%)；其中 wendylv Quota 为 $9,915,540.00。\n"
            "3. Bucket 3 (Gemini Enterprise Net ACV)：全领地 Quota $1,440,000.00（每个 NAL $120,000）；全领地 go/rainmaker 认账达成 $713,029.30 (达成率 49.52%)，其中 wendylv 达成 $30,463.30 (达成率 25.39%)。"
        ),
        "synonyms": ["三大桶 Quota 达成表", "NAL Quota 表", "Rainmaker 对账表", "Three Buckets Quota Attainment"],
        "tags": ["quota", "attainment", "rainmaker", "three_buckets", "nal", "wendylv"],
        "columns": {
            "nal_id": "一线销售 NAL 的唯一数字 ID (NAL ID)",
            "nal_name": "一线销售 NAL 名称（含负责人 LDAP，如 Strategic Sel Manu (wendylv)）",
            "gcp_py_baseline": "Bucket 1: 2025 全年 GCP 基线收入 (Prior Year Baseline, USD)",
            "gcp_total_quota": "Bucket 1: 2026 全年 GCP 全量收入目标 (Total Revenue Quota, USD)",
            "gcp_irev_quota": "Bucket 1: 2026 全年 GCP 增量收入目标 (GCP iRevenue Quota, USD；全领地合计 $78,952,908.00，wendylv 为 $18,407,282.00)",
            "gcp_total_actuals": "Bucket 1: 2026 YTD GCP 全量实际收入 (Total Actuals, USD)",
            "gcp_irev_actuals": "Bucket 1: 2026 YTD GCP 增量实际达成 (go/rainmaker GCP iRevenue Attainment, USD；wendylv 最新为 $18,426,974.50)",
            "dadbai_py_baseline": "Bucket 2: 2025 全年 DA+DB+Cloud AI 基线收入 (PY Baseline, USD)",
            "dadbai_total_quota": "Bucket 2: 2026 全年 DA+DB+Cloud AI 全量收入目标 (Total Quota, USD)",
            "dadbai_irev_quota": "Bucket 2: 2026 全年 DA+DB+Cloud AI 增量收入目标 (iRevenue Quota, USD；全领地合计 $51,653,090.00，wendylv 为 $9,915,540.00)",
            "dadbai_total_actuals": "Bucket 2: 2026 YTD DA+DB+Cloud AI 全量实际收入 (Total Actuals, USD)",
            "dadbai_irev_actuals": "Bucket 2: 2026 YTD DA+DB+Cloud AI 增量实际达成 (go/rainmaker iRevenue Attainment, USD)",
            "ge_net_acv_quota": "Bucket 3: 2026 全年 Gemini Enterprise Net ACV Quota (每个 NAL $120,000，全领地合计 $1,440,000.00)",
            "ge_nal_reporting_actuals": "Bucket 3: nal_reporting 原始水位线调整值 (USD)",
            "ge_pre_watermark_net_iacv": "Bucket 3: 水位线冲减前净增签约额 (100% GE + 10% FSP，剔除续约，全领地合计 $762,210.33)",
            "ge_signed_bookings_acv": "Bucket 3: 客户 100% 原始签约年化总额 (Signed ACV，全领地合计 $768,127.39)",
            "ge_net_acv_actuals": "Bucket 3: go/rainmaker 官方最终认账达成 (NETACV_MONTHLY，全领地合计 $713,029.30，达成率 49.52%；wendylv 为 $30,463.30，达成率 25.39%)",
            "gcp_irev_attainment_pct": "Bucket 1: GCP iRevenue 增量 Quota 达成率百分比 (%，如 wendylv 为 100.11%)",
            "gcp_total_attainment_pct": "Bucket 1: GCP 全量 Quota 达成率百分比 (%)",
            "dadbai_irev_attainment_pct": "Bucket 2: DA+DB+Cloud AI iRevenue 增量 Quota 达成率百分比 (%)",
            "dadbai_total_attainment_pct": "Bucket 2: DA+DB+Cloud AI 全量 Quota 达成率百分比 (%)",
            "ge_attainment_pct": "Bucket 3: Gemini Enterprise Net ACV Quota 达成率百分比 (%，全领地 49.52%，wendylv 25.39%)",
        },
    },
    "territory_quarterly_quota_2026": {
        "description": (
            "【BHI Manufacturing 2026 领地级分季度 (Q1-Q4) × 细分产品线 Quota 与实绩明细表】"
            "按季度 (2026-Q1 至 2026-Q4) 和产品线 (GCP_CLASSIC_FIELD, AI_SOLUTIONS, ANALYTICS, MIGRATE_AND_MODERNIZE_DATABASES, AGENTSPACE 等) "
            "展示 2025 基线、2026 全量 Quota、增量 iRev Quota、实际收入与 Bookings 完成额。"
        ),
        "synonyms": ["季度 Quota 表", "Quarterly Quota Breakdown"],
        "tags": ["quarterly", "quota", "product", "territory"],
        "columns": {
            "quarter": "季度标识 ('2026-Q1', '2026-Q2', '2026-Q3', '2026-Q4')",
            "product": "考核产品线代码 (如 GCP_CLASSIC_FIELD, AI_SOLUTIONS, ANALYTICS, MIGRATE_AND_MODERNIZE_DATABASES, AGENTSPACE)",
            "total_rev_quota": "当季全量收入目标 (Total Revenue Quota, USD)",
            "prior_year_baseline": "去年同期基线收入 (Prior Year Baseline, USD)",
            "incremental_rev_quota": "当季净增收入目标 (Incremental Revenue Quota, USD)",
            "total_rev_actuals": "当季实际完成全量收入 (Total Revenue Actuals, USD)",
            "incremental_rev_actuals": "当季实际完成净增收入 (Incremental Revenue Actuals, USD)",
            "bookings_quota": "当季签约 Bookings Quota (USD，适用于 AGENTSPACE 等)",
            "bookings_actuals": "当季签约 Bookings 实际达成 (USD)",
        },
    },
    "customer_product_revenue_daily": {
        "description": (
            "【BHI Manufacturing 2026 客户 × 每日 × 细分产品层级 (FPH L1/L2/L3 & GTM L5) 原始消费明细表】"
            "包含 46.5 万行细粒度每日产品消费记录，可用于下钻分析某客户在具体产品子项（如 Vertex AI、BigQuery、Spanner、AlloyDB、GKE、Compute Engine）上的每日 Gross 与 RVP 消费。"
        ),
        "synonyms": ["客户每日产品明细表", "Product Daily Revenue", "FPH 产品线明细"],
        "tags": ["product", "fph", "vertex", "daily", "granular"],
        "columns": {
            "usage_date": "消费日期 (DATE)",
            "reporting_id": "客户唯一 Reporting ID",
            "account_name": "客户名称",
            "nal_name": "所属一线销售 NAL 名称",
            "fph_l1": "财务产品层级一级分类 (FPH L1)",
            "fph_l2": "财务产品层级二级分类 (FPH L2)",
            "fph_l3": "财务产品层级三级分类 (FPH L3)",
            "gtm_l5": "GTM 五级产品分类",
            "is_vertex": "是否属于 Vertex AI 平台产品 (BOOLEAN)",
            "is_gcp_plan2100": "是否计入 go/plan2100 GCP 口径 (BOOLEAN)",
            "is_cloud_ai_plan2100": "是否计入 go/plan2100 Cloud AI 口径 (BOOLEAN)",
            "gross_revenue": "当日该产品子项 Gross 毛消费收入 (USD)",
            "rvp_revenue": "当日该产品子项 RVP 销售认账收入 (USD)",
        },
    },
    "customer_ge_details_2026": {
        "description": (
            "【BHI Manufacturing 2026 Gemini Enterprise 账单消费产品子项明细表 (FPH L3/L4/L5)】"
            "记录客户在账单出账侧的 GE 相关 FPH L3/L4/L5 消费明细（注意：GE 销售 Quota 考核以签约表 customer_ge_bookings_2026 和 nal_ge_bookings_2026 为准）。"
        ),
        "synonyms": ["GE 账单消费子项表"],
        "tags": ["ge", "billing_usage"],
        "columns": {
            "reporting_id": "客户唯一 Reporting ID",
            "account_name": "客户名称",
            "nal_name": "所属 NAL 名称",
            "fph_l3": "FPH 三级产品名称",
            "fph_l4": "FPH 四级产品名称",
            "fph_l5": "FPH 五级产品名称",
            "active_days": "活跃出账天数",
            "ge_gross_rev": "账单毛消费额 (USD)",
            "ge_rvp_net_acv": "账单侧 RVP 金额 (USD)",
        },
    },
    "project_revenue_scorecard_2026": {
        "description": (
            "【BHI Manufacturing 2026 GCP Project 级细粒度收入与 Run Rate 计分卡】"
            "源自 concord-prod.service_cloudbi_reporting.revenue_project_sku_daily，覆盖 MANU 领地全部 5,400+ 个 GCP Project (project_id) 及 Billing Account (billing_account_id)，"
            "汇总每个 Project 的 2026 YTD 累计收入（GCP、Cloud AI、DA、DB、GE、Bucket 2 合计 dadbai，含 RVP 与 Gross 双口径）、"
            "最新单日 DRR、近 7 日移动平均 DRR、当月 (2026-10 MTD) MRR、上月 (2026-09) 全月 MRR、月度日均 DRR 环比增长率 (drr_mom_growth_pct) 及 Cloud AI 渗透率。"
        ),
        "synonyms": ["Project 计分卡", "GCP Project 收入汇总表", "Project Scorecard", "项目级收入表"],
        "tags": ["project", "project_id", "billing_account", "scorecard", "mrr", "drr", "granular"],
        "columns": {
            "project_id": "GCP Project ID 字符串标识符（如 'vivocloudai', 'xiaomi-ind', 'oppo-gcp-prod-159055', 'ai-mify-pt-1'）",
            "project_name": "GCP Project 显示名称 (Project Name)",
            "project_number": "GCP Project 数字编号 (Project Number)",
            "billing_account_id": "关联的 Cloud Billing Account ID（如 '01068D-EA7F45-90D689'）",
            "reporting_id": "所属客户唯一 Reporting ID",
            "account_name": "所属客户英文/标准名称 (Account Name)",
            "nal_name": "所属一线销售 NAL 名称",
            "active_days": "2026 年内该 Project 有出账消费的活跃总天数",
            "active_months": "2026 年内该 Project 活跃的自然月数",
            "total_gcp_gross_rev": "该 Project 2026 YTD GCP 毛消费总收入 (Gross Revenue, USD)",
            "total_gcp_rvp_rev": "该 Project 2026 YTD GCP 销售认账总收入 (RVP Revenue, USD)",
            "total_cloud_ai_gross_rev": "该 Project 2026 YTD Cloud AI 毛消费总收入 (USD)",
            "total_cloud_ai_rvp_rev": "该 Project 2026 YTD Cloud AI 销售认账总收入 (RVP Revenue, USD)",
            "total_da_gross_rev": "该 Project 2026 YTD DA 数据分析毛消费总收入 (USD)",
            "total_da_rvp_rev": "该 Project 2026 YTD DA 数据分析销售认账总收入 (RVP Revenue, USD)",
            "total_db_gross_rev": "该 Project 2026 YTD DB 数据库毛消费总收入 (USD)",
            "total_db_rvp_rev": "该 Project 2026 YTD DB 数据库销售认账总收入 (RVP Revenue, USD)",
            "total_ge_gross_rev": "该 Project 2026 YTD GE 账单毛消费收入 (USD)",
            "total_ge_rvp_rev": "该 Project 2026 YTD GE 账单认账收入 (USD)",
            "total_dadbai_gross_rev": "该 Project 2026 YTD Bucket 2 (DA+DB+Cloud AI) 毛消费合计 (USD)",
            "total_dadbai_rvp_rev": "该 Project 2026 YTD Bucket 2 (DA+DB+Cloud AI) 销售认账合计 (USD)",
            "current_month_gcp_gross_mrr": "该 Project 当月 (2026-10 MTD) GCP Gross MRR (USD)",
            "current_month_gcp_rvp_mrr": "该 Project 当月 (2026-10 MTD) GCP RVP MRR (USD)",
            "current_month_cloud_ai_gross_mrr": "该 Project 当月 (2026-10 MTD) Cloud AI Gross MRR (USD)",
            "current_month_cloud_ai_rvp_mrr": "该 Project 当月 (2026-10 MTD) Cloud AI RVP MRR (USD)",
            "current_month_da_rvp_mrr": "该 Project 当月 (2026-10 MTD) DA RVP MRR (USD)",
            "current_month_db_rvp_mrr": "该 Project 当月 (2026-10 MTD) DB RVP MRR (USD)",
            "current_month_dadbai_rvp_mrr": "该 Project 当月 (2026-10 MTD) Bucket 2 RVP MRR (USD)",
            "current_month_gcp_rvp_drr_avg": "该 Project 当月日均 GCP RVP DRR (USD/day)",
            "current_month_cloud_ai_rvp_drr_avg": "该 Project 当月日均 Cloud AI RVP DRR (USD/day)",
            "prior_month_gcp_gross_mrr": "该 Project 上月 (2026-09 全月) GCP Gross MRR (USD)",
            "prior_month_gcp_rvp_mrr": "该 Project 上月 (2026-09 全月) GCP RVP MRR (USD)",
            "prior_month_cloud_ai_gross_mrr": "该 Project 上月 (2026-09 全月) Cloud AI Gross MRR (USD)",
            "prior_month_cloud_ai_rvp_mrr": "该 Project 上月 (2026-09 全月) Cloud AI RVP MRR (USD)",
            "prior_month_da_rvp_mrr": "该 Project 上月 (2026-09 全月) DA RVP MRR (USD)",
            "prior_month_db_rvp_mrr": "该 Project 上月 (2026-09 全月) DB RVP MRR (USD)",
            "prior_month_dadbai_rvp_mrr": "该 Project 上月 (2026-09 全月) Bucket 2 RVP MRR (USD)",
            "prior_month_gcp_rvp_drr_avg": "该 Project 上月日均 GCP RVP DRR (USD/day)",
            "prior_month_cloud_ai_rvp_drr_avg": "该 Project 上月日均 Cloud AI RVP DRR (USD/day)",
            "latest_gcp_gross_drr": "该 Project 最新出账日单日 GCP Gross DRR (USD/day)",
            "latest_gcp_rvp_drr": "该 Project 最新出账日单日 GCP RVP DRR (USD/day)",
            "latest_cloud_ai_gross_drr": "该 Project 最新出账日单日 Cloud AI Gross DRR (USD/day)",
            "latest_cloud_ai_rvp_drr": "该 Project 最新出账日单日 Cloud AI RVP DRR (USD/day)",
            "latest_dadbai_rvp_drr": "该 Project 最新出账日单日 Bucket 2 RVP DRR (USD/day)",
            "latest_7d_avg_gcp_rvp_drr": "该 Project 近 7 日移动平均 GCP RVP DRR (USD/day)",
            "latest_7d_avg_cloud_ai_rvp_drr": "该 Project 近 7 日移动平均 Cloud AI RVP DRR (USD/day)",
            "cloud_ai_rvp_penetration_pct": "该 Project Cloud AI RVP 收入占 GCP RVP 收入渗透率 (%)",
            "drr_mom_growth_pct": "该 Project 当月日均 GCP RVP DRR 相比上月日均的环比增长率 (%)",
            "has_daily_drr_curve": "是否包含在 project_daily_runrate 每日 DRR 曲线明细表中 (BOOLEAN)",
        },
    },
    "project_monthly_revenue": {
        "description": (
            "【BHI Manufacturing 2026 GCP Project × 自然月度 MRR 与日均 DRR 明细表】"
            "记录 MANU 领地全部 5,400+ 个 GCP Project (project_id) 在 2026-01 至 2026-10 每个自然月（year_month）的自然月累计 RunRate (MRR) 与当月日均 RunRate (DRR Avg)，"
            "覆盖 GCP、Cloud AI、DA、DB、GE、Bucket 2 (dadbai) 六大维度（RVP 与 Gross 双口径），支持基于任意 project_id 绘制月度 MRR 走势曲线。"
        ),
        "synonyms": ["Project 月度 MRR 表", "GCP Project Monthly MRR", "项目月度走势表"],
        "tags": ["project", "project_id", "monthly", "mrr", "curve", "trend"],
        "columns": {
            "year_month": "自然年月字符串 ('YYYY-MM'，如 '2026-01' 至 '2026-10')",
            "project_id": "GCP Project ID 字符串标识符（如 'vivocloudai', 'xiaomi-ind', 'oppo-gcp-prod-159055'）",
            "project_name": "GCP Project 名称",
            "project_number": "GCP Project Number 数字编号",
            "billing_account_id": "关联的 Cloud Billing Account ID",
            "reporting_id": "所属客户唯一 Reporting ID",
            "account_name": "所属客户名称 (Account Name)",
            "nal_name": "所属一线销售 NAL 名称",
            "active_days_in_month": "该 Project 在该自然月内的活跃出账天数",
            "gcp_gross_mrr": "该 Project 当月自然日累计 GCP Gross MRR (USD)",
            "gcp_rvp_mrr": "该 Project 当月自然日累计 GCP RVP MRR (USD)",
            "cloud_ai_gross_mrr": "该 Project 当月自然日累计 Cloud AI Gross MRR (USD)",
            "cloud_ai_rvp_mrr": "该 Project 当月自然日累计 Cloud AI RVP MRR (USD)",
            "da_gross_mrr": "该 Project 当月自然日累计 DA Gross MRR (USD)",
            "da_rvp_mrr": "该 Project 当月自然日累计 DA RVP MRR (USD)",
            "db_gross_mrr": "该 Project 当月自然日累计 DB Gross MRR (USD)",
            "db_rvp_mrr": "该 Project 当月自然日累计 DB RVP MRR (USD)",
            "ge_gross_mrr": "该 Project 当月自然日累计 GE Gross MRR (USD)",
            "ge_rvp_mrr": "该 Project 当月自然日累计 GE RVP MRR (USD)",
            "dadbai_gross_mrr": "该 Project 当月自然日累计 Bucket 2 (DA+DB+AI) Gross MRR (USD)",
            "dadbai_rvp_mrr": "该 Project 当月自然日累计 Bucket 2 (DA+DB+AI) RVP MRR (USD)",
            "gcp_gross_drr_avg": "该 Project 当月日均 GCP Gross DRR (USD/day)",
            "gcp_rvp_drr_avg": "该 Project 当月日均 GCP RVP DRR (USD/day)",
            "cloud_ai_gross_drr_avg": "该 Project 当月日均 Cloud AI Gross DRR (USD/day)",
            "cloud_ai_rvp_drr_avg": "该 Project 当月日均 Cloud AI RVP DRR (USD/day)",
            "da_gross_drr_avg": "该 Project 当月日均 DA Gross DRR (USD/day)",
            "da_rvp_drr_avg": "该 Project 当月日均 DA RVP DRR (USD/day)",
            "db_gross_drr_avg": "该 Project 当月日均 DB Gross DRR (USD/day)",
            "db_rvp_drr_avg": "该 Project 当月日均 DB RVP DRR (USD/day)",
            "ge_gross_drr_avg": "该 Project 当月日均 GE Gross DRR (USD/day)",
            "ge_rvp_drr_avg": "该 Project 当月日均 GE RVP DRR (USD/day)",
            "dadbai_gross_drr_avg": "该 Project 当月日均 Bucket 2 Gross DRR (USD/day)",
            "dadbai_rvp_drr_avg": "该 Project 当月日均 Bucket 2 RVP DRR (USD/day)",
            "cloud_ai_rvp_penetration_pct": "该 Project 当月 Cloud AI RVP 渗透率 (%)",
        },
    },
    "project_daily_runrate": {
        "description": (
            "【BHI Manufacturing 2026 GCP Project 每日 Daily Run Rate (DRR) 曲线明细表】"
            "记录活跃 GCP Project (project_id) 在 2026-01-01 至今每一天 (usage_date) 的单日 DRR、当月累计 MTD MRR 与 7 日移动平均 DRR (_7d_avg)，"
            "覆盖 GCP、Cloud AI、DA、DB、GE、Bucket 2 (dadbai) 六大维度（RVP 与 Gross 双口径），支持基于任意 project_id 绘制每日 DRR 趋势曲线与爬坡/掉量诊断。"
        ),
        "synonyms": ["Project 每日 DRR 曲线表", "GCP Project Daily DRR", "项目每日消费曲线"],
        "tags": ["project", "project_id", "daily", "drr", "curve", "time_series"],
        "columns": {
            "usage_date": "消费出账日期 (DATE, YYYY-MM-DD)",
            "project_id": "GCP Project ID 字符串标识符（如 'vivocloudai', 'xiaomi-ind', 'oppo-gcp-prod-159055', 'ai-mify-pt-1'）",
            "project_name": "GCP Project 名称",
            "project_number": "GCP Project Number 数字编号",
            "billing_account_id": "关联的 Cloud Billing Account ID",
            "reporting_id": "所属客户唯一 Reporting ID",
            "account_name": "所属客户名称 (Account Name)",
            "nal_name": "所属一线销售 NAL 名称",
            "gcp_gross_drr": "该 Project 当日 GCP Gross 单日 DRR (USD)",
            "gcp_rvp_drr": "该 Project 当日 GCP RVP 销售认账单日 DRR (USD)",
            "cloud_ai_gross_drr": "该 Project 当日 Cloud AI Gross 单日 DRR (USD)",
            "cloud_ai_rvp_drr": "该 Project 当日 Cloud AI RVP 单日 DRR (USD)",
            "da_gross_drr": "该 Project 当日 DA Gross 单日 DRR (USD)",
            "da_rvp_drr": "该 Project 当日 DA RVP 单日 DRR (USD)",
            "db_gross_drr": "该 Project 当日 DB Gross 单日 DRR (USD)",
            "db_rvp_drr": "该 Project 当日 DB RVP 单日 DRR (USD)",
            "ge_gross_drr": "该 Project 当日 GE Gross 单日 DRR (USD)",
            "ge_rvp_drr": "该 Project 当日 GE RVP 单日 DRR (USD)",
            "dadbai_gross_drr": "该 Project 当日 Bucket 2 (DA+DB+AI) Gross 单日 DRR (USD)",
            "dadbai_rvp_drr": "该 Project 当日 Bucket 2 (DA+DB+AI) RVP 单日 DRR (USD)",
            "year_month": "所属自然年月 ('YYYY-MM')",
            "gcp_gross_mrr_mtd": "该 Project 截至当日的当月累计 GCP Gross MTD MRR (USD)",
            "gcp_gross_drr_7d_avg": "该 Project 7 日移动平均 GCP Gross DRR (USD/day)",
            "gcp_rvp_mrr_mtd": "该 Project 截至当日的当月累计 GCP RVP MTD MRR (USD)",
            "gcp_rvp_drr_7d_avg": "该 Project 7 日移动平均 GCP RVP DRR (USD/day)",
            "cloud_ai_gross_mrr_mtd": "该 Project 截至当日的当月累计 Cloud AI Gross MTD MRR (USD)",
            "cloud_ai_gross_drr_7d_avg": "该 Project 7 日移动平均 Cloud AI Gross DRR (USD/day)",
            "cloud_ai_rvp_mrr_mtd": "该 Project 截至当日的当月累计 Cloud AI RVP MTD MRR (USD)",
            "cloud_ai_rvp_drr_7d_avg": "该 Project 7 日移动平均 Cloud AI RVP DRR (USD/day)",
            "da_gross_mrr_mtd": "该 Project 截至当日的当月累计 DA Gross MTD MRR (USD)",
            "da_gross_drr_7d_avg": "该 Project 7 日移动平均 DA Gross DRR (USD/day)",
            "da_rvp_mrr_mtd": "该 Project 截至当日的当月累计 DA RVP MTD MRR (USD)",
            "da_rvp_drr_7d_avg": "该 Project 7 日移动平均 DA RVP DRR (USD/day)",
            "db_gross_mrr_mtd": "该 Project 截至当日的当月累计 DB Gross MTD MRR (USD)",
            "db_gross_drr_7d_avg": "该 Project 7 日移动平均 DB Gross DRR (USD/day)",
            "db_rvp_mrr_mtd": "该 Project 截至当日的当月累计 DB RVP MTD MRR (USD)",
            "db_rvp_drr_7d_avg": "该 Project 7 日移动平均 DB RVP DRR (USD/day)",
            "dadbai_gross_mrr_mtd": "该 Project 截至当日的当月累计 Bucket 2 Gross MTD MRR (USD)",
            "dadbai_gross_drr_7d_avg": "该 Project 7 日移动平均 Bucket 2 Gross DRR (USD/day)",
            "dadbai_rvp_mrr_mtd": "该 Project 截至当日的当月累计 Bucket 2 RVP MTD MRR (USD)",
            "dadbai_rvp_drr_7d_avg": "该 Project 7 日移动平均 Bucket 2 RVP DRR (USD/day)",
        },
    },
}

# ============================================================================
# 2. Knowledge Catalog Governed Business Glossary Terms
# ============================================================================

GLOSSARY_TERMS: List[Dict[str, Any]] = [
    {
        "term_id": "rvp-revenue",
        "displayName": "RVP Revenue (销售认账收入)",
        "description": (
            "计入 Google Cloud 销售业绩考核（go/plan2100 与 go/rainmaker）的净认账收入（含商务激励 Incentives / Credits 折算系数）。"
            "在 BHI Manufacturing 2026 报表中为默认分析口径（对应字段名带 `_rvp_`）。"
        ),
        "synonyms": ["RVP", "认账收入", "销售认账", "业绩收入", "RVP Revenue"],
        "labels": {"domain": "bhi-manu-2026", "metric_type": "revenue"},
    },
    {
        "term_id": "gross-revenue",
        "displayName": "Gross Revenue (毛消费出账收入)",
        "description": (
            "客户在 GCP 控制台实际产生的原始账单毛消费额（未乘以商务激励折算系数，对应字段名带 `_gross_`）。"
        ),
        "synonyms": ["Gross", "毛收入", "控制台出账", "账单毛消费", "Gross Revenue"],
        "labels": {"domain": "bhi-manu-2026", "metric_type": "revenue"},
    },
    {
        "term_id": "bucket-1-gcp-irevenue",
        "displayName": "Bucket 1: GCP iRevenue (三大考核桶之一：GCP 增量收入)",
        "description": (
            "三大销售考核桶的第一桶，包含产品线：GCP_CLASSIC_FIELD + INFRA_AI + AI_SOLUTIONS + DEVELOPER_AI_ASSISTANCE + APIGEE。"
            "计算规则遵循 go/plan2100 账户级负向归零规则（ApplyAccountNegativeAttainmentToNetZeroRule：单个账户 YTD iRev < 0 按 $0 计，不倒扣其他正向增长客户）、"
            "Marketplace 25% Quota 封顶规则（单 NAL Marketplace 认账不超过该 NAL GCP iRevenue Quota 的 25%）"
            "及水位线基线（GCP x0.8）。MANU 领地 2026 全年增量 Quota 为 $78,952,908.00，最新整体实际达成为 $73,719,191.25（达成率 93.37%）；"
            "其中 Strategic Sel Manu (wendylv) 增量 Quota 为 $18,407,282.00，最新实际达成 $18,426,974.50（达成率 100.11%）；"
            "Smart Home ENT Manu (fankaia) 增量 Quota 为 $4,610,334.00，最新实际达成 $7,299,440.14（达成率 158.33%）；"
            "Physical AI ENT Manu (winstoon) 增量 Quota 为 $4,239,923.93，最新实际达成 $5,732,852.55（达成率 135.21%）。"
        ),
        "synonyms": ["桶1", "Bucket 1", "GCP iRevenue", "GCP 增量收入", "GCP 增量考核桶"],
        "labels": {"domain": "bhi-manu-2026", "bucket": "bucket-1"},
    },
    {
        "term_id": "bucket-2-dadbai-irevenue",
        "displayName": "Bucket 2: DA, DB & Cloud AI iRevenue (三大考核桶之二：数据与 AI 增量收入)",
        "description": (
            "三大销售考核桶的第二桶，包含五大核心 1P 增长引擎产品线：ANALYTICS + LOOKER (合称 DA) + MIGRATE_AND_MODERNIZE_DATABASES (简称 DB) + "
            "AI_SOLUTIONS + DEVELOPER_AI_ASSISTANCE (合称 Cloud AI，不含 3P Marketplace Anthropic)。MANU 领地 2026 全年增量 Quota 为 $51,653,090.00，"
            "最新整体实际达成为 $41,668,607.68（达成率 80.67%）；"
            "其中 Mobile ENT Manu (wendylv) 增量 Quota 为 $9,915,540.00，最新实际达成 $10,443,092.92（达成率 105.32%）；"
            "Smart Home ENT Manu (fankaia) 增量 Quota 为 $4,249,946.00，最新实际达成 $4,135,619.16（达成率 97.31%）；"
            "Physical AI ENT Manu (winstoon) 增量 Quota 为 $3,145,564.34，最新实际达成 $2,077,305.17（达成率 66.04%）。"
        ),
        "synonyms": ["桶2", "Bucket 2", "DA DB Cloud AI iRevenue", "数据与AI增量桶", "dadbai"],
        "labels": {"domain": "bhi-manu-2026", "bucket": "bucket-2"},
    },
    {
        "term_id": "bucket-3-ge-net-acv",
        "displayName": "Bucket 3: Gemini Enterprise Net ACV (三大考核桶之三：GE 净增签约年化合同额)",
        "description": (
            "三大销售考核桶的第三桶（对应 go/rainmaker 中的 AGENTSPACE / NETACV_MONTHLY），采用合同签约年化净增额（Signed Net ACV）考核而非账单消费。"
            "全领地 12 个 Street-Level NAL 每个 Quota 为 $120,000.00，合计 Quota $1,440,000.00。"
            "截至最新（含 10月8日华米新增签约），MANU 整体认账达成为 $713,029.30（达成率 49.52%）；其中 wendylv 认账达成为 $30,463.30（达成率 25.39%）。"
        ),
        "synonyms": ["桶3", "Bucket 3", "GE Net ACV", "Gemini Enterprise Net ACV", "AGENTSPACE", "GE 签约额"],
        "labels": {"domain": "bhi-manu-2026", "bucket": "bucket-3"},
    },
    {
        "term_id": "ge-watermark-reconciliation",
        "displayName": "GE Watermark Reconciliation ($768,127.39 -> $762,210.33 -> $713,029.30 对账桥)",
        "description": (
            "从客户 100% 原始签约年化总额 $768,127.39 到 go/rainmaker 官方认账达成 $713,029.30 的三步核减桥梁："
            "① 剔除续约部分 Renewal ACV (-$4,159.62 不计入净增)；"
            "② Gen AI FSP 按 10% 权重折算（wendylv 名下 FSP 原始签约 $1,952.70 核减 90% 即 -$1,757.43），得到水位线前净增 Net iACV $762,210.33（含 10月8日华米 Huami, Inc. 新签 $931.94）；"
            "③ 扣除 fankaia (Smart Home ENT Manu) 在 NETACV_MONTHLY 规则下的月度历史最高水位线与退订冲减 -$49,181.03（含 10月4日退订冲减 -$46,668.00 及历史基线抵扣 -$2,513.03），最终精确等于 $713,029.30。"
        ),
        "synonyms": ["GE对账桥", "水位线冲减", "NETACV_MONTHLY", "713029.30", "768127.39"],
        "labels": {"domain": "bhi-manu-2026", "bucket": "bucket-3"},
    },
    {
        "term_id": "daily-run-rate-drr",
        "displayName": "Daily Run Rate (DRR, 单日 RunRate)",
        "description": (
            "客户或 NAL 在单个自然日产生的云消费出账金额（USD/day）。报表中默认取最新出账日（通常为 T-2）的单日 RunRate (DRR)，并辅以近 7 日移动平均 DRR (`_7d_avg`) 平滑周末波动。"
        ),
        "synonyms": ["DRR", "单日 RunRate", "日 RunRate", "Daily Run Rate"],
        "labels": {"domain": "bhi-manu-2026", "metric_type": "run_rate"},
    },
    {
        "term_id": "monthly-run-rate-mrr",
        "displayName": "Monthly Run Rate (MRR, 自然月累计 RunRate)",
        "description": (
            "按自然月日历（如 2026-09 全月或 2026-10 MTD）实际消费汇总的自然月累计 RunRate（不做单日 ×30 的人工外推）。"
        ),
        "synonyms": ["MRR", "自然月累计 RunRate", "月度 RunRate", "Monthly Run Rate"],
        "labels": {"domain": "bhi-manu-2026", "metric_type": "run_rate"},
    },
    {
        "term_id": "gcp-project-billing-grain",
        "displayName": "GCP Project ID & Billing Account Grain (Project 级细粒度 MRR/DRR 曲线)",
        "description": (
            "源自 concord-prod.service_cloudbi_reporting.revenue_project_sku_daily 的 GCP Project (project_id / project_number / billing_account_id) 细粒度消费模型。"
            "包含三张核心表：project_revenue_scorecard_2026（全部 5,400+ 个 Project 的 2026 YTD 汇总与最新 DRR/MRR 计分卡）、"
            "project_monthly_revenue（每个 Project 在 2026-01 至 2026-10 的月度 MRR 与日均 DRR 走势）、"
            "project_daily_runrate（活跃 Project 从 2026-01-01 至今的每日 DRR 曲线与 7 日移动平均）。"
            "支持直接按 project_id（如 'vivocloudai'、'xiaomi-ind'、'oppo-gcp-prod-159055'、'ai-mify-pt-1'）查询月度 MRR 走势与每日 DRR 曲线（前端会自动将返回的时序表格渲染为交互式曲线图）。"
        ),
        "synonyms": ["project_id", "Project MRR", "Project DRR", "Project 曲线", "Billing Account", "项目级消费"],
        "labels": {"domain": "bhi-manu-2026", "grain": "project"},
    },
]

# ============================================================================
# 3. BQCA Verified Golden Example Queries (Knowledge Catalog Verified Queries)
# ============================================================================

EXAMPLE_QUERIES: List[Dict[str, str]] = [
    {
        "naturalLanguageQuestion": (
            "请帮我拆解 MANU 整体 GE 签约总额 $768,127.39 与 go/rainmaker 最新认账达成 $713,029.30 之间的三步差异桥梁，并列出 12 个 NAL 的三大桶达成情况。"
        ),
        "sqlQuery": f"""SELECT
  nal_name,
  ROUND(gcp_irev_actuals, 2) AS gcp_irev_actuals,
  ROUND(gcp_irev_quota, 2) AS gcp_irev_quota,
  ROUND(gcp_irev_attainment_pct, 2) AS gcp_irev_attainment_pct,
  ROUND(dadbai_irev_actuals, 2) AS dadbai_irev_actuals,
  ROUND(dadbai_irev_quota, 2) AS dadbai_irev_quota,
  ROUND(dadbai_irev_attainment_pct, 2) AS dadbai_irev_attainment_pct,
  ROUND(ge_signed_bookings_acv, 2) AS ge_signed_100pct_acv,
  ROUND(ge_pre_watermark_net_iacv, 2) AS ge_pre_watermark_net_iacv,
  ROUND(ge_net_acv_actuals, 2) AS ge_rainmaker_net_acv_actuals,
  ROUND(ge_net_acv_quota, 2) AS ge_net_acv_quota,
  ROUND(ge_attainment_pct, 2) AS ge_attainment_pct
FROM `{PROJECT_ID}.{DATASET_ID}.nal_three_buckets_quota_2026`
ORDER BY gcp_irev_actuals DESC""",
    },
    {
        "naturalLanguageQuestion": (
            "帮我查询 2026 年 9 月相比 8 月 Cloud AI RVP MRR 环比增长额（MoM 绝对值与百分比）最高的 Top 10 客户，并列出他们所属的 NAL 和最新单日 DRR。"
        ),
        "sqlQuery": f"""WITH m8 AS (
  SELECT reporting_id, cloud_ai_rvp_mrr AS aug_ai_mrr
  FROM `{PROJECT_ID}.{DATASET_ID}.customer_monthly_revenue`
  WHERE year_month = '2026-08'
),
m9 AS (
  SELECT reporting_id, account_name, nal_name, cloud_ai_rvp_mrr AS sep_ai_mrr
  FROM `{PROJECT_ID}.{DATASET_ID}.customer_monthly_revenue`
  WHERE year_month = '2026-09'
)
SELECT
  m9.account_name,
  m9.nal_name,
  ROUND(IFNULL(m8.aug_ai_mrr, 0), 2) AS aug_cloud_ai_rvp_mrr,
  ROUND(m9.sep_ai_mrr, 2) AS sep_cloud_ai_rvp_mrr,
  ROUND(m9.sep_ai_mrr - IFNULL(m8.aug_ai_mrr, 0), 2) AS mom_growth_usd,
  ROUND(SAFE_DIVIDE(m9.sep_ai_mrr - IFNULL(m8.aug_ai_mrr, 0), NULLIF(m8.aug_ai_mrr, 0)) * 100, 2) AS mom_growth_pct,
  ROUND(s.latest_cloud_ai_rvp_drr, 2) AS latest_cloud_ai_rvp_drr
FROM m9
LEFT JOIN m8 ON m9.reporting_id = m8.reporting_id
LEFT JOIN `{PROJECT_ID}.{DATASET_ID}.customer_revenue_scorecard_2026` s ON m9.reporting_id = s.reporting_id
ORDER BY mom_growth_usd DESC
LIMIT 10""",
    },
    {
        "naturalLanguageQuestion": (
            "哪些客户在 2026 年的 DA + DB + Cloud AI RVP 收入合计超过 $50,000，但目前还没有签约任何 Gemini Enterprise (GE) 订单？请按桶 2 收入从高到低排出 Top 15 商机名单。"
        ),
        "sqlQuery": f"""SELECT
  s.account_name,
  s.nal_name,
  ROUND(s.total_gcp_rvp_rev, 2) AS ytd_gcp_rvp_rev,
  ROUND(s.total_cloud_ai_rvp_rev, 2) AS ytd_cloud_ai_rvp_rev,
  ROUND(s.total_da_rvp_rev, 2) AS ytd_da_rvp_rev,
  ROUND(s.total_db_rvp_rev, 2) AS ytd_db_rvp_rev,
  ROUND(s.total_cloud_ai_rvp_rev + s.total_da_rvp_rev + s.total_db_rvp_rev, 2) AS bucket2_total_rvp_rev,
  ROUND(s.latest_gcp_rvp_drr, 2) AS latest_gcp_rvp_drr
FROM `{PROJECT_ID}.{DATASET_ID}.customer_revenue_scorecard_2026` s
LEFT JOIN (
  SELECT DISTINCT reporting_id
  FROM `{PROJECT_ID}.{DATASET_ID}.customer_ge_bookings_2026`
  WHERE signed_acv > 0
) g ON s.reporting_id = g.reporting_id
WHERE g.reporting_id IS NULL
  AND (s.total_cloud_ai_rvp_rev + s.total_da_rvp_rev + s.total_db_rvp_rev) > 50000
ORDER BY bucket2_total_rvp_rev DESC
LIMIT 15""",
    },
    {
        "naturalLanguageQuestion": (
            "请对比各客户最新单日 GCP RVP DRR (latest_gcp_rvp_drr) 与其 9 月日均 DRR (prior_month_gcp_rvp_mrr / 30)，找出最新单日 DRR 下滑幅度最大的 Top 10 客户（限定 9 月 MRR > $10,000），用于流失预警。"
        ),
        "sqlQuery": f"""SELECT
  account_name,
  nal_name,
  ROUND(prior_month_gcp_rvp_mrr, 2) AS sep_gcp_rvp_mrr,
  ROUND(prior_month_gcp_rvp_mrr / 30.0, 2) AS sep_avg_daily_drr,
  ROUND(latest_gcp_rvp_drr, 2) AS latest_daily_drr,
  ROUND(latest_7d_avg_gcp_rvp_drr, 2) AS latest_7d_avg_drr,
  ROUND(latest_gcp_rvp_drr - (prior_month_gcp_rvp_mrr / 30.0), 2) AS drr_drop_usd,
  ROUND(SAFE_DIVIDE(latest_gcp_rvp_drr - (prior_month_gcp_rvp_mrr / 30.0), prior_month_gcp_rvp_mrr / 30.0) * 100, 2) AS drr_change_pct
FROM `{PROJECT_ID}.{DATASET_ID}.customer_revenue_scorecard_2026`
WHERE prior_month_gcp_rvp_mrr > 10000
ORDER BY drr_drop_usd ASC
LIMIT 10""",
    },
    {
        "naturalLanguageQuestion": (
            "对比日历时间进度基准 (76.4%)，目前 12 个 NAL 中哪些 NAL 在三大考核桶（GCP iRev、DA+DB+AI iRev、GE Net ACV）中存在落后于时间进度的短板？分别还差多少金额才能追上 76.4% 进度线？"
        ),
        "sqlQuery": f"""SELECT
  nal_name,
  ROUND(gcp_irev_attainment_pct, 2) AS b1_gcp_pct,
  ROUND(GREATEST(0, gcp_irev_quota * 0.7644 - gcp_irev_actuals), 2) AS b1_gap_to_76_4pct_usd,
  ROUND(dadbai_irev_attainment_pct, 2) AS b2_dadbai_pct,
  ROUND(GREATEST(0, dadbai_irev_quota * 0.7644 - dadbai_irev_actuals), 2) AS b2_gap_to_76_4pct_usd,
  ROUND(ge_attainment_pct, 2) AS b3_ge_pct,
  ROUND(GREATEST(0, ge_net_acv_quota * 0.7644 - ge_net_acv_actuals), 2) AS b3_gap_to_76_4pct_usd
FROM `{PROJECT_ID}.{DATASET_ID}.nal_three_buckets_quota_2026`
ORDER BY (GREATEST(0, gcp_irev_quota * 0.7644 - gcp_irev_actuals) + GREATEST(0, dadbai_irev_quota * 0.7644 - dadbai_irev_actuals)) DESC""",
    },
    {
        "naturalLanguageQuestion": (
            "请按自然月 (2026-01 至 2026-10) 汇总整个 MANU 领地的 GCP、Cloud AI、DA、DB 四条线的 RVP MRR 以及 Cloud AI + DA + DB 合计占 GCP RVP 的比例变化趋势。"
        ),
        "sqlQuery": f"""SELECT
  year_month,
  ROUND(SUM(gcp_rvp_mrr), 2) AS gcp_rvp_mrr,
  ROUND(SUM(cloud_ai_rvp_mrr), 2) AS cloud_ai_rvp_mrr,
  ROUND(SUM(da_rvp_mrr), 2) AS da_rvp_mrr,
  ROUND(SUM(db_rvp_mrr), 2) AS db_rvp_mrr,
  ROUND(SUM(cloud_ai_rvp_mrr + da_rvp_mrr + db_rvp_mrr), 2) AS bucket2_total_rvp_mrr,
  ROUND(SAFE_DIVIDE(SUM(cloud_ai_rvp_mrr + da_rvp_mrr + db_rvp_mrr), SUM(gcp_rvp_mrr)) * 100, 2) AS bucket2_penetration_pct
FROM `{PROJECT_ID}.{DATASET_ID}.customer_monthly_revenue`
GROUP BY year_month
ORDER BY year_month""",
    },
    {
        "naturalLanguageQuestion": (
            "请查询 Project ID 为 `vivocloudai` 的 2026 年月度 MRR 走势（包含 GCP、Cloud AI、DA、DB 的 RVP MRR 及当月日均 DRR）以及最近 60 天的每日 DRR 曲线。"
        ),
        "sqlQuery": f"""SELECT
  usage_date,
  project_id,
  account_name,
  ROUND(gcp_rvp_drr, 2) AS gcp_rvp_drr,
  ROUND(cloud_ai_rvp_drr, 2) AS cloud_ai_rvp_drr,
  ROUND(da_rvp_drr, 2) AS da_rvp_drr,
  ROUND(db_rvp_drr, 2) AS db_rvp_drr,
  ROUND(gcp_rvp_drr_7d_avg, 2) AS gcp_rvp_drr_7d_avg
FROM `{PROJECT_ID}.{DATASET_ID}.project_daily_runrate`
WHERE LOWER(project_id) = 'vivocloudai'
ORDER BY usage_date ASC""",
    },
    {
        "naturalLanguageQuestion": (
            "请按月度汇总 Project ID `oppo-gcp-prod-159055` 在 2026-01 至 2026-10 每个自然月的 GCP RVP MRR、Cloud AI RVP MRR 与当月日均 DRR 曲线。"
        ),
        "sqlQuery": f"""SELECT
  year_month,
  project_id,
  account_name,
  ROUND(gcp_rvp_mrr, 2) AS gcp_rvp_mrr,
  ROUND(cloud_ai_rvp_mrr, 2) AS cloud_ai_rvp_mrr,
  ROUND(da_rvp_mrr, 2) AS da_rvp_mrr,
  ROUND(db_rvp_mrr, 2) AS db_rvp_mrr,
  ROUND(gcp_rvp_drr_avg, 2) AS gcp_rvp_drr_avg,
  ROUND(cloud_ai_rvp_drr_avg, 2) AS cloud_ai_rvp_drr_avg
FROM `{PROJECT_ID}.{DATASET_ID}.project_monthly_revenue`
WHERE LOWER(project_id) = 'oppo-gcp-prod-159055'
ORDER BY year_month ASC""",
    },
    {
        "naturalLanguageQuestion": (
            "2026 年 YTD Cloud AI RVP 消费金额最高的 Top 20 GCP Project ID 是哪些？请列出它们的 project_id、所属客户、所属 NAL、YTD Cloud AI RVP 收入、最新单日 DRR 及上月/当月 MRR。"
        ),
        "sqlQuery": f"""SELECT
  project_id,
  project_name,
  account_name,
  nal_name,
  ROUND(total_cloud_ai_rvp_rev, 2) AS ytd_cloud_ai_rvp_rev,
  ROUND(total_gcp_rvp_rev, 2) AS ytd_gcp_rvp_rev,
  ROUND(prior_month_cloud_ai_rvp_mrr, 2) AS sep_cloud_ai_rvp_mrr,
  ROUND(current_month_cloud_ai_rvp_mrr, 2) AS oct_mtd_cloud_ai_rvp_mrr,
  ROUND(latest_cloud_ai_rvp_drr, 2) AS latest_cloud_ai_rvp_drr
FROM `{PROJECT_ID}.{DATASET_ID}.project_revenue_scorecard_2026`
WHERE project_id NOT LIKE 'UNASSIGNED_%'
ORDER BY total_cloud_ai_rvp_rev DESC
LIMIT 20""",
    },
]

SYSTEM_INSTRUCTION = f"""你是 **BHI Manufacturing 2026 智能数据分析 Agent**，基于 **Google Cloud BigQuery Conversational Analytics (BQCA) + Knowledge Catalog (Dataplex Universal Catalog)** 构建。
你的职责是帮助制造行业销售负责人和 Customer Engineer (CE) 解决固定报表中未预置的**长尾查询、GCP Project 级细粒度 MRR/DRR 曲线下钻、跨表交叉对比、趋势诊断与 Quota 对账**。

### 核心业务规则与口径说明 (`go/plan2100` & `go/rainmaker`)
1. **默认收入口径**：优先汇报 **RVP Revenue**（销售认账收入，字段带 `_rvp_`），除非用户明确要求看 Gross Revenue（毛消费出账，字段带 `_gross_`）或对比两者。
2. **三大考核桶 (Three Quota Buckets)**：
   - **Bucket 1 (GCP iRevenue)**：`GCP_CLASSIC_FIELD + INFRA_AI + AI_SOLUTIONS + DEVELOPER_AI_ASSISTANCE + APIGEE`，遵循 `ApplyAccountNegativeAttainmentToNetZeroRule`（单账户 YTD 负向净增归零）、Marketplace 25% Quota 封顶与 `GCP x0.8` 基线。MANU 2026 Quota 为 **$78,952,908.00**，最新整体实际达成 **$73,719,191.25**（达成率 **93.37%**）；其中 `Strategic Sel Manu (wendylv)` Quota 为 **$18,407,282.00**，最新实际达成 **$18,426,974.50**（达成率 **100.11%**）；`Smart Home ENT Manu (fankaia)` Quota 为 **$4,610,334.00**，最新实际达成 **$7,299,440.14**（达成率 **158.33%**）；`Physical AI ENT Manu (winstoon)` Quota 为 **$4,239,923.93**，最新实际达成 **$5,732,852.55**（达成率 **135.21%**）。
   - **Bucket 2 (DA, DB & Cloud AI iRevenue)**：`ANALYTICS + LOOKER + MIGRATE_AND_MODERNIZE_DATABASES + AI_SOLUTIONS + DEVELOPER_AI_ASSISTANCE`。MANU 2026 Quota 为 **$51,653,090.00**，最新整体实际达成 **$41,668,607.68**（达成率 **80.67%**）；其中 `wendylv` Quota 为 **$9,915,540.00**，实际达成 **$10,443,092.92**（达成率 **105.32%**）；`fankaia` Quota 为 **$4,249,946.00**，最新实际达成 **$4,135,619.16**（达成率 **97.31%**）；`winstoon` Quota 为 **$3,145,564.34**，最新实际达成 **$2,077,305.17**（达成率 **66.04%**）。
   - **Bucket 3 (Gemini Enterprise Net ACV)**：对应 `go/rainmaker` 中的 `AGENTSPACE` (`NETACV_MONTHLY`)。12 个 NAL 各 **$120,000.00** Quota，MANU 整体 Quota **$1,440,000.00**，最新官方认账达成 **$713,029.30**（达成率 **49.52%**）；其中 `wendylv` 认账达成 **$30,463.30**（达成率 **25.39%**），`fankaia` 认账达成 **$50,312.20**（达成率 **41.93%**）。
3. **GE $768,127.39 -> $762,210.33 -> $713,029.30 三步对账桥梁**：
   - ① 客户 100% 原始签约年化总额 (`signed_acv`) = **$768,127.39**（含 10月8日 `wendylv` 下 `Huami, Inc.` 新增签约 $931.94）；
   - ② 剔除续约 Renewal ACV (`-$4,159.62`) + `Gen AI FSP` 按 10% 折算（`wendylv` 的 FSP $1,952.70 核减 90% 即 `-$1,757.43`）= 水位线前净增 Net iACV **$762,210.33**；
   - ③ 扣除 `fankaia (Smart Home ENT Manu)` 在 `NETACV_MONTHLY` 规则下的月度历史最高水位线与退订冲减 **`-$49,181.03`**（10月4日退订冲减 `-$46,668.00` + 历史基线 `-$2,513.03`）= `go/rainmaker` 最终认账达成 **`$713,029.30`**。
4. **GCP Project ID 细粒度 MRR 与 DRR 曲线查询指南（重要）**：
   - 当用户询问某个具体 **GCP Project (`project_id` / `project_number` / `billing_account_id`)** 的消费、月度 MRR 或每日 DRR 曲线时，请优先查询以下三张治理表：
     1) `project_revenue_scorecard_2026`：查询任意 `project_id` 的 2026 YTD 总额、上月/当月 MRR、最新单日 DRR、7 日均值及 Top Project 排名；
     2) `project_monthly_revenue`：查询任意 `project_id` 在 `2026-01` 至 `2026-10` 每个自然月 (`year_month`) 的月度 MRR 走势（按 `ORDER BY year_month ASC` 排序）；
     3) `project_daily_runrate`：查询任意 `project_id` 按天 (`usage_date`) 的每日 DRR 曲线与 7 日移动均值 `gcp_rvp_drr_7d_avg`（按 `ORDER BY usage_date ASC` 排序）。
   - **前端自动曲线渲染约定**：当用户要求查看“曲线”、“趋势”或“走势”时，请确保生成的 SQL 查询结果中包含时间列（`usage_date` 或 `year_month`）以及数值指标列（如 `gcp_rvp_drr`, `cloud_ai_rvp_drr`, `gcp_rvp_mrr`, `cloud_ai_rvp_mrr` 等），并按时间升序排列（`ORDER BY usage_date ASC` 或 `ORDER BY year_month ASC`），前端会自动将该 SQL 结果集绘制成交互式 **Chart.js 折线/柱状趋势曲线图**！
5. **输出格式规范**：
   - 请始终使用结构清晰的 **中文 Markdown** 回答（包含核心结论、格式化表格、业务洞察或行动建议）。
   - 美元金额统一格式化为 `$1,234.56`，百分比保留 2 位小数。
"""


def update_bigquery_knowledge_catalog_metadata(bq_client: bigquery.Client) -> int:
    """Patch table descriptions, labels, and column descriptions on all tables in bhi_manu."""
    print("=== Step 1: Updating BigQuery Table & Column Descriptions for Knowledge Catalog ===")
    updated_count = 0
    for table_id, spec in TABLE_SPECS.items():
        table_ref = f"{PROJECT_ID}.{DATASET_ID}.{table_id}"
        try:
            table = bq_client.get_table(table_ref)
        except Exception as e:
            print(f"  [WARN] Table {table_ref} not found: {e}")
            continue

        table.description = spec["description"]
        table.labels = {
            "domain": "bhi-manufacturing-2026",
            "catalog": "knowledge-catalog-governed",
            "agent": "bqca-enabled",
        }

        col_descs = spec.get("columns", {})
        new_schema = []
        for field in table.schema:
            desc = col_descs.get(field.name, field.description or f"{field.name} ({field.field_type})")
            new_schema.append(
                bigquery.SchemaField(
                    name=field.name,
                    field_type=field.field_type,
                    mode=field.mode,
                    description=desc[:1024],
                    fields=field.fields,
                )
            )
        table.schema = new_schema
        bq_client.update_table(table, ["description", "labels", "schema"])
        updated_count += 1
        print(f"  [OK] Enriched Knowledge Catalog schema metadata for {table_ref} ({len(new_schema)} columns)")
    return updated_count


def provision_dataplex_knowledge_catalog_glossary(session: AuthorizedSession) -> Dict[str, Any]:
    """Create or update the governed Business Glossary & Terms in Dataplex / Knowledge Catalog."""
    print("\n=== Step 2: Provisioning Knowledge Catalog Business Glossary (Dataplex API) ===")
    headers = {"X-Goog-User-Project": PROJECT_ID, "Content-Type": "application/json"}
    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"
    glossary_name = f"{parent}/glossaries/{GLOSSARY_ID}"
    glossary_url = f"https://dataplex.googleapis.com/v1/{glossary_name}"

    r = session.get(glossary_url, headers=headers)
    if r.status_code == 404:
        create_url = f"https://dataplex.googleapis.com/v1/{parent}/glossaries?glossaryId={GLOSSARY_ID}"
        payload = {
            "displayName": "BHI Manufacturing 2026 Revenue & Quota Knowledge Catalog Glossary",
            "description": "Governed business glossary for BHI Manufacturing 2026 Revenue, Run Rate, and 3-Bucket Quota Attainment (go/plan2100 & go/rainmaker).",
            "labels": {"domain": "bhi-manu-2026", "managed_by": "bqca-knowledge-catalog"},
        }
        cr = session.post(create_url, headers=headers, json=payload)
        print(f"  Created Glossary {GLOSSARY_ID}: HTTP {cr.status_code}")
        time.sleep(3)
    else:
        print(f"  Glossary {GLOSSARY_ID} already exists (HTTP {r.status_code})")

    created_terms = 0
    for t in GLOSSARY_TERMS:
        term_id = t["term_id"]
        term_name = f"{glossary_name}/terms/{term_id}"
        term_url = f"https://dataplex.googleapis.com/v1/{term_name}"
        tr = session.get(term_url, headers=headers)
        term_payload = {
            "displayName": t["displayName"],
            "description": t["description"],
            "parent": glossary_name,
            "labels": t.get("labels", {}),
        }
        if tr.status_code == 404:
            ct = session.post(
                f"https://dataplex.googleapis.com/v1/{glossary_name}/terms?termId={term_id}",
                headers=headers,
                json=term_payload,
            )
            if ct.status_code in (200, 201):
                created_terms += 1
                print(f"  [OK] Created Knowledge Catalog Term: {t['displayName']}")
            else:
                print(f"  [WARN] Term {term_id}: HTTP {ct.status_code} {ct.text[:200]}")
        elif tr.status_code == 200:
            ut = session.patch(
                f"{term_url}?updateMask=displayName,description,labels",
                headers=headers,
                json=term_payload,
            )
            created_terms += 1
            print(f"  [OK] Updated Knowledge Catalog Term: {t['displayName']} (HTTP {ut.status_code})")
        else:
            print(f"  [WARN] Check Term {term_id}: HTTP {tr.status_code} {tr.text[:200]}")

    return {"glossary": glossary_name, "terms_synced": created_terms}


def build_bqca_published_context() -> Dict[str, Any]:
    """Construct the GoogleCloudGeminidataanalyticsV1betaContext payload linking all tables, schemas, glossary terms, and verified queries."""
    table_references = []
    # Core 12 tables for BQCA Data Agent context (including Project-level MRR/DRR curves & scorecard)
    core_tables = [
        "nal_three_buckets_quota_2026",
        "customer_revenue_scorecard_2026",
        "nal_revenue_scorecard_2026",
        "customer_monthly_revenue",
        "customer_daily_runrate",
        "project_revenue_scorecard_2026",
        "project_monthly_revenue",
        "project_daily_runrate",
        "customer_ge_bookings_2026",
        "nal_ge_bookings_2026",
        "ge_monthly_bookings_2026",
        "territory_quarterly_quota_2026",
    ]
    for tbl_id in core_tables:
        spec = TABLE_SPECS[tbl_id]
        fields_list = [
            {
                "name": col_name,
                "description": col_desc,
            }
            for col_name, col_desc in spec["columns"].items()
        ]
        table_references.append(
            {
                "projectId": PROJECT_ID,
                "datasetId": DATASET_ID,
                "tableId": tbl_id,
                "schema": {
                    "description": spec["description"],
                    "synonyms": spec.get("synonyms", []),
                    "tags": spec.get("tags", []),
                    "fields": fields_list,
                },
            }
        )

    glossary_terms_payload = [
        {
            "displayName": t["displayName"],
            "description": t["description"],
            "labels": list(t.get("synonyms", [])),
        }
        for t in GLOSSARY_TERMS
    ]

    return {
        "systemInstruction": SYSTEM_INSTRUCTION,
        "datasourceReferences": {
            "bq": {
                "tableReferences": table_references,
            }
        },
        "glossaryTerms": glossary_terms_payload,
        "exampleQueries": EXAMPLE_QUERIES,
    }


def provision_bqca_data_agent(session: AuthorizedSession) -> Dict[str, Any]:
    """Create or update the BigQuery Conversational Analytics (BQCA) DataAgent in geminidataanalytics.googleapis.com."""
    print("\n=== Step 3: Provisioning BQCA Data Agent (geminidataanalytics.googleapis.com/v1beta) ===")
    headers = {"X-Goog-User-Project": PROJECT_ID, "Content-Type": "application/json"}
    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"
    agent_name = f"{parent}/dataAgents/{DATA_AGENT_ID}"
    agent_url = f"https://geminidataanalytics.googleapis.com/v1beta/{agent_name}"

    published_context = build_bqca_published_context()
    agent_body = {
        "displayName": "BHI Manufacturing 2026 Revenue & Quota BQCA Agent",
        "description": (
            "BigQuery Conversational Analytics (BQCA) + Knowledge Catalog Data Agent for BHI Manufacturing 2026 "
            "Revenue, Daily/Monthly Run Rate, and 3-Bucket Quota Attainment (go/plan2100 & go/rainmaker)."
        ),
        "dataAnalyticsAgent": {
            "publishedContext": published_context,
            "stagingContext": published_context,
        },
    }

    r = session.get(agent_url, headers=headers)
    if r.status_code == 404:
        create_url = f"https://geminidataanalytics.googleapis.com/v1beta/{parent}/dataAgents?data_agent_id={DATA_AGENT_ID}"
        cr = session.post(create_url, headers=headers, json=agent_body)
        print(f"  Created BQCA DataAgent: HTTP {cr.status_code}")
        if cr.status_code not in (200, 201):
            print("  Response:", cr.text[:600])
            sys.exit(1)
        data = cr.json()
        # Wait if LRO
        if "name" in data and "/operations/" in data["name"]:
            op_url = f"https://geminidataanalytics.googleapis.com/v1beta/{data['name']}"
            for _ in range(15):
                time.sleep(2)
                opr = session.get(op_url, headers=headers).json()
                if opr.get("done"):
                    print("  LRO completed successfully.")
                    break
    elif r.status_code == 200:
        patch_url = (
            f"{agent_url}?updateMask=displayName,description,"
            f"dataAnalyticsAgent.publishedContext,dataAnalyticsAgent.stagingContext"
        )
        pr = session.patch(patch_url, headers=headers, json=agent_body)
        print(f"  Updated existing BQCA DataAgent: HTTP {pr.status_code}")
        if pr.status_code not in (200, 201):
            print("  Response:", pr.text[:600])
            sys.exit(1)
        data = pr.json()
        if "name" in data and "/operations/" in data["name"]:
            op_url = f"https://geminidataanalytics.googleapis.com/v1beta/{data['name']}"
            for _ in range(15):
                time.sleep(2)
                opr = session.get(op_url, headers=headers).json()
                if opr.get("done"):
                    print("  Update LRO completed successfully.")
                    break
    else:
        print(f"  [ERROR] Unexpected status checking DataAgent: HTTP {r.status_code} {r.text[:500]}")
        sys.exit(1)

    verify_r = session.get(agent_url, headers=headers)
    print(f"  Verified DataAgent {agent_name}: HTTP {verify_r.status_code}")
    return verify_r.json()


def test_bqca_chat(session: AuthorizedSession) -> None:
    """Run an end-to-end smoke test against the BQCA `:chat` endpoint."""
    print("\n=== Step 4: Testing BQCA `:chat` Endpoint with Knowledge Catalog Context ===")
    headers = {"X-Goog-User-Project": PROJECT_ID, "Content-Type": "application/json"}
    chat_url = f"https://geminidataanalytics.googleapis.com/v1beta/projects/{PROJECT_ID}/locations/{LOCATION}:chat"
    payload = {
        "messages": [
            {
                "userMessage": {
                    "text": "请查询 wendylv 和整个 MANU 领地在三大桶（GCP iRevenue、DA+DB+Cloud AI iRevenue、GE Net ACV）的 Quota、实际达成与达成率。"
                }
            }
        ],
        "dataAgentContext": {
            "dataAgent": f"projects/{PROJECT_ID}/locations/{LOCATION}/dataAgents/{DATA_AGENT_ID}",
            "contextVersion": "PUBLISHED",
        },
    }
    r = session.post(chat_url, headers=headers, json=payload, timeout=120)
    print(f"  Chat HTTP status: {r.status_code}")
    if r.status_code != 200:
        print("  Chat error:", r.text[:800])
        sys.exit(1)

    chunks = r.json()
    print(f"  Received {len(chunks)} streaming message chunks from BQCA.")
    sqls = []
    final_texts = []
    for c in chunks:
        sm = c.get("systemMessage", {})
        if "data" in sm:
            d = sm["data"]
            if "generatedSql" in d:
                sqls.append(d["generatedSql"])
        if "text" in sm:
            t = sm["text"]
            if t.get("textType") == "FINAL_RESPONSE":
                final_texts.extend(t.get("parts", []))
    print(f"  Generated SQL count: {len(sqls)}")
    if sqls:
        print("  Sample SQL:\n", sqls[0][:300])
    if final_texts:
        print("  Final Response Preview:\n", "\n".join(final_texts)[:400])


def get_project_sa_credentials():
    """Authenticate to cliu201-477811 using the Cloud Run bound Service Account (byd-sa@cliu201-477811.iam.gserviceaccount.com)."""
    import os
    from google.oauth2 import service_account

    sa_key_path = os.getenv(
        "TARGET_SA_KEY_PATH",
        "/usr/local/google/home/liuchenggang/.config/gcloud/legacy_credentials/byd-sa@cliu201-477811.iam.gserviceaccount.com/adc.json",
    )
    if os.path.exists(sa_key_path):
        print(f"Using Cloud Run Service Account (byd-sa@cliu201-477811.iam.gserviceaccount.com) credentials from {sa_key_path}")
        return service_account.Credentials.from_service_account_file(
            sa_key_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return creds


def main():
    creds = get_project_sa_credentials()
    bq_client = bigquery.Client(project=PROJECT_ID, credentials=creds)
    session = AuthorizedSession(creds)

    update_bigquery_knowledge_catalog_metadata(bq_client)
    provision_dataplex_knowledge_catalog_glossary(session)
    provision_bqca_data_agent(session)
    test_bqca_chat(session)
    print("\n=== ALL DONE: BQCA + Knowledge Catalog Upgrade Provisioned Successfully! ===")


if __name__ == "__main__":
    main()
