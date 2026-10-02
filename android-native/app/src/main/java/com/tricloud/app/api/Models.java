package com.tricloud.app.api;

import java.util.List;
import java.util.Map;

public class Models {

    public static class Provider {
        public String id;
        public String name;
    }

    public static class CloudAccount {
        public int id;
        public String provider;
        public String name;
    }

    public static class Instance {
        public String id;
        public String name;
        public String status;
        public String public_ip;
        public String private_ip;
        public String region;
        public String shape;
        public Map<String, Object> extra;
    }

    public static class Billing {
        public double total;
        public String currency;
        public String period;
        public Double credit_used;
        public List<BillingService> services;
    }

    public static class BillingService {
        public String name;
        public double cost;
    }

    public static class LightsailInstance {
        public String name;
        public String state;
        public String blueprint;
        public String bundle;
        public String public_ip;
        public String private_ip;
        public String region;
        public String zone;
    }

    public static class Distribution {
        public String id;
        public String domain;
        public String status;
        public boolean enabled;
        public String comment;
        public String plan;
    }

    public static class Job {
        public String id;
        public String type;
        public String provider;
        public String title;
        public String status;
        public String log;
        public String result;
        public double created_at;
        public Double finished_at;
    }
}
