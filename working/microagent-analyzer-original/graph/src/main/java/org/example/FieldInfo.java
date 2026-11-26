package org.example;

import java.util.ArrayList;
import java.util.List;

/**
 * Stores information about a class field, including its type, name, and annotations
 */
public class FieldInfo {
    private String name;
    private String type;           // The fully resolved type name
    private String originalType;   // The original type name as it appears in the source
    private List<String> annotations = new ArrayList<>();
    private boolean isPrivate;
    private boolean isPublic;
    private boolean isProtected;
    private boolean isStatic;
    private boolean isFinal;
    
    public FieldInfo(String name, String type, String originalType) {
        this.name = name;
        this.type = type;
        this.originalType = originalType;
    }
    
    public void addAnnotation(String annotation) {
        annotations.add(annotation);
    }
    
    public String getName() {
        return name;
    }
    
    public String getType() {
        return type;
    }
    
    public String getOriginalType() {
        return originalType;
    }
    
    public List<String> getAnnotations() {
        return annotations;
    }
    
    public boolean isPrivate() {
        return isPrivate;
    }
    
    public void setPrivate(boolean isPrivate) {
        this.isPrivate = isPrivate;
    }
    
    public boolean isPublic() {
        return isPublic;
    }
    
    public void setPublic(boolean isPublic) {
        this.isPublic = isPublic;
    }
    
    public boolean isProtected() {
        return isProtected;
    }
    
    public void setProtected(boolean isProtected) {
        this.isProtected = isProtected;
    }
    
    public boolean isStatic() {
        return isStatic;
    }
    
    public void setStatic(boolean isStatic) {
        this.isStatic = isStatic;
    }
    
    public boolean isFinal() {
        return isFinal;
    }
    
    public void setFinal(boolean isFinal) {
        this.isFinal = isFinal;
    }
    
    /**
     * Get the field declaration as a string
     */
    public String getDeclaration() {
        StringBuilder sb = new StringBuilder();
        
        // Add modifiers
        if (isPublic) sb.append("public ");
        if (isPrivate) sb.append("private ");
        if (isProtected) sb.append("protected ");
        if (isStatic) sb.append("static ");
        if (isFinal) sb.append("final ");
        
        // Add type and name
        sb.append(originalType).append(" ").append(name);
        
        return sb.toString();
    }
} 