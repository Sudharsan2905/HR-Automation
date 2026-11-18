from enum import Enum


class UmbrellaDomain(str, Enum):
    """Top-level domain categories."""
    TECH = "tech"
    BDE = "bde"
    HR = "hr"


class TechDomain(str, Enum):
    """Tech domain titles."""
    FRONTEND_ENGINEERING = "Frontend Engineering"
    BACKEND_ENGINEERING = "Backend Engineering"
    AI_ML = "AI / Machine Learning"
    DATA_ENGINEERING = "Data Engineering"
    DEVOPS_CLOUD = "DevOps & Cloud"
    QA_TESTING = "QA / Testing"
    MOBILE_DEVELOPMENT = "Mobile Development"
    SECURITY_ENGINEERING = "Security Engineering"
    SYSTEM_DESIGN = "System Design"
    FULL_STACK = "Full Stack"
    GEN_AI = "Gen AI"


class BDEDomain(str, Enum):
    """BDE domain titles."""
    BUSINESS_DEVELOPMENT = "Business Development"
    SALES_STRATEGY = "Sales Strategy"
    CLIENT_RELATIONSHIP = "Client Relationship Management"
    MARKET_RESEARCH = "Market Research"


class HRDomain(str, Enum):
    """HR domain titles."""
    RECRUITMENT = "Recruitment & Talent Acquisition"
    EMPLOYEE_RELATIONS = "Employee Relations"
    PERFORMANCE_MANAGEMENT = "Performance Management"
    HR_OPERATIONS = "HR Operations"
    LEARNING_DEVELOPMENT = "Learning & Development"


UMBRELLA_DOMAIN_MAP: dict[UmbrellaDomain, type[Enum]] = {
    UmbrellaDomain.TECH: TechDomain,
    UmbrellaDomain.BDE: BDEDomain,
    UmbrellaDomain.HR: HRDomain,
}

DOMAIN_REGISTRY: dict[UmbrellaDomain, list[dict]] = {
    UmbrellaDomain.TECH: [
        {
            "title": TechDomain.FRONTEND_ENGINEERING.value,
            "highlights": [
                "UI Development",
                "Browser Architecture",
                "Performance Optimization",
                "Accessibility",
                "State Management",
            ],
        },
        {
            "title": TechDomain.BACKEND_ENGINEERING.value,
            "highlights": [
                "API Development",
                "Distributed Systems",
                "Authentication & Authorization",
                "Concurrency & Scalability",
                "Microservices",
            ],
        },
        {
            "title": TechDomain.AI_ML.value,
            "highlights": [
                "Machine Learning",
                "Deep Learning",
                "Natural Language Processing",
                "Generative AI",
                "MLOps",
            ],
        },
        {
            "title": TechDomain.DATA_ENGINEERING.value,
            "highlights": [
                "Data Pipelines",
                "Data Warehousing",
                "Big Data Processing",
                "Data Modeling",
                "Streaming Systems",
            ],
        },
        {
            "title": TechDomain.DEVOPS_CLOUD.value,
            "highlights": [
                "CI/CD Pipelines",
                "Containerization",
                "Infrastructure Automation",
                "Cloud Architecture",
                "Monitoring & Observability",
            ],
        },
        {
            "title": TechDomain.QA_TESTING.value,
            "highlights": [
                "Unit Testing",
                "Integration Testing",
                "Test Automation",
                "Performance Testing",
                "QA Strategy",
            ],
        },
        {
            "title": TechDomain.MOBILE_DEVELOPMENT.value,
            "highlights": [
                "Mobile Architecture",
                "Cross-Platform Apps",
                "Performance Optimization",
                "Offline Systems",
                "App Security",
            ],
        },
        {
            "title": TechDomain.SECURITY_ENGINEERING.value,
            "highlights": [
                "Secure Coding",
                "Application Security",
                "Identity Management",
                "Encryption",
                "Vulnerability Analysis",
            ],
        },
        {
            "title": TechDomain.SYSTEM_DESIGN.value,
            "highlights": [
                "Scalability",
                "High Availability",
                "Load Balancing",
                "Distributed Systems",
                "Fault Tolerance",
            ],
        },
        {
            "title": TechDomain.FULL_STACK.value,
            "highlights": [
                "End-to-End Development",
                "API Integration",
                "Frontend & Backend",
                "Full Lifecycle Delivery",
                "Architecture Decisions",
            ],
        },
        {
            "title": TechDomain.GEN_AI.value,
            "highlights": [
                "LLM Integration",
                "Prompt Engineering",
                "RAG Pipelines",
                "AI Agents",
                "Vector Databases",
            ],
        },
    ],
    UmbrellaDomain.BDE: [
        {
            "title": BDEDomain.BUSINESS_DEVELOPMENT.value,
            "highlights": [
                "Opportunity Identification",
                "Market Expansion",
                "Strategic Partnerships",
                "Business Strategy",
            ],
        },
        {
            "title": BDEDomain.SALES_STRATEGY.value,
            "highlights": [
                "Sales Pipeline",
                "Prospect Qualification",
                "Sales Forecasting",
                "Competitive Positioning",
            ],
        },
        {
            "title": BDEDomain.CLIENT_RELATIONSHIP.value,
            "highlights": [
                "Client Engagement",
                "Stakeholder Communication",
                "Relationship Building",
                "Long-Term Retention",
            ],
        },
        {
            "title": BDEDomain.MARKET_RESEARCH.value,
            "highlights": [
                "Industry Analysis",
                "Competitor Research",
                "Customer Insights",
                "Opportunity Mapping",
            ],
        },
    ],
    UmbrellaDomain.HR: [
        {
            "title": HRDomain.RECRUITMENT.value,
            "highlights": [
                "Candidate Sourcing",
                "Interview Evaluation",
                "Hiring Strategy",
                "Employer Branding",
            ],
        },
        {
            "title": HRDomain.EMPLOYEE_RELATIONS.value,
            "highlights": [
                "Workplace Communication",
                "Conflict Resolution",
                "Employee Engagement",
                "Workplace Support",
            ],
        },
        {
            "title": HRDomain.PERFORMANCE_MANAGEMENT.value,
            "highlights": [
                "Performance Reviews",
                "Goal Setting",
                "Feedback Systems",
                "Improvement Plans",
            ],
        },
        {
            "title": HRDomain.HR_OPERATIONS.value,
            "highlights": [
                "HR Policies",
                "Documentation",
                "Payroll Coordination",
                "Employee Lifecycle",
            ],
        },
        {
            "title": HRDomain.LEARNING_DEVELOPMENT.value,
            "highlights": [
                "Training Programs",
                "Skill Development",
                "Leadership Training",
                "Career Growth",
            ],
        },
    ],
}
