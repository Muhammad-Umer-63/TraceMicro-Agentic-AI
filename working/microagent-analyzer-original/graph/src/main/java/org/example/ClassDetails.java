package org.example;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Stores detailed information about a class, including its imports, annotations, methods, and fields
 */
public class ClassDetails {
    private String className;
    private Set<String> imports = new HashSet<>();
    private List<String> annotations = new ArrayList<>();
    private List<MethodInfo> methods = new ArrayList<>();
    private List<FieldInfo> fields = new ArrayList<>();
    private List<String> innerClasses = new ArrayList<>();
    private Map<String, List<String>> innerClassAnnotations = new HashMap<>();
    private Map<String, String> metadata = new HashMap<>();
    
    public ClassDetails(String className) {
        this.className = className;
    }
    
    public String getClassName() {
        return className;
    }
    
    public void addImport(String importName) {
        imports.add(importName);
    }
    
    public void addAnnotation(String annotation) {
        annotations.add(annotation);
    }
    
    public void addMethod(MethodInfo method) {
        methods.add(method);
    }
    
    public void addField(FieldInfo field) {
        fields.add(field);
    }
    
    public void addInnerClass(String innerClassName) {
        if (!innerClasses.contains(innerClassName)) {
            innerClasses.add(innerClassName);
        }
    }
    
    public void addInnerClassAnnotation(String innerClassName, String annotation) {
        innerClassAnnotations
            .computeIfAbsent(innerClassName, k -> new ArrayList<>())
            .add(annotation);
    }
    
    /**
     * Add or update metadata for this class
     */
    public void addMetadata(String key, String value) {
        metadata.put(key, value);
    }
    
    /**
     * Get metadata value by key
     */
    public String getMetadata(String key) {
        return metadata.get(key);
    }
    
    /**
     * Get all metadata
     */
    public Map<String, String> getAllMetadata() {
        return new HashMap<>(metadata);
    }
    
    public List<String> getInnerClasses() {
        return innerClasses;
    }
    
    public List<String> getInnerClassAnnotations(String innerClassName) {
        return innerClassAnnotations.getOrDefault(innerClassName, new ArrayList<>());
    }
    
    public Set<String> getImports() {
        return imports;
    }
    
    public List<String> getAnnotations() {
        return annotations;
    }
    
    public List<MethodInfo> getMethods() {
        return methods;
    }
    
    public List<FieldInfo> getFields() {
        return fields;
    }
    
    public void setImports(Set<String> imports) {
        this.imports = imports;
    }
} 