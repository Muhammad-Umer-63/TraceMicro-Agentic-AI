package org.example;

/**
 * Represents a relationship between two classes
 */
public class Relationship {
    private String targetClass;
    private RelationshipType type;
    private int count;
    
    public Relationship(String targetClass, RelationshipType type) {
        this.targetClass = targetClass;
        this.type = type;
        this.count = 1;
    }
    
    public String getTargetClass() {
        return targetClass;
    }
    
    public RelationshipType getType() {
        return type;
    }
    
    public int getCount() {
        return count;
    }
    
    public void incrementCount() {
        count++;
    }
    
    @Override
    public String toString() {
        return type + " -> " + targetClass;
    }
} 